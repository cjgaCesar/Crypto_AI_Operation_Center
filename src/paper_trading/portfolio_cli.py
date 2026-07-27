"""
CLI operativa y estrictamente de solo lectura para consultar el estado
de Paper Trading (Etapa 6.18).

Uso:
    python -m src.paper_trading.portfolio_cli summary
    python -m src.paper_trading.portfolio_cli positions --status open
    python -m src.paper_trading.portfolio_cli orders --status PENDING --limit 20
    python -m src.paper_trading.portfolio_cli alerts --status PENDING
    python -m src.paper_trading.portfolio_cli deliveries --alert-id <ID>
    python -m src.paper_trading.portfolio_cli summary --format json

Decisión arquitectónica (ver docs/ARQUITECTURA_PAPER_TRADING.md §33.1):
ni `SQLitePaperTradingRepository` ni el adaptador de solo lectura del
Dashboard (`RepositoryPaperTradingDashboardRepository`) abren TODAS sus
conexiones en modo real de solo lectura (`file:...?mode=ro`) -- ambos
solo evitan LLAMAR métodos de escritura, que no es la misma garantía.
Esta CLI implementa su propia capa mínima de consultas SQL, sobre una
conexión SQLite abierta siempre en `mode=ro` (§9 de esta etapa: "no
basta con no llamar métodos save"). Reutiliza únicamente funciones
puras de `serialization.py` (Decimal/datetime <-> texto, sin ninguna
dependencia de sqlite3) -- nunca `PaperTradingService`/`RiskEngine`/
`FillEngine`/`PositionEngine`/`ReservationEngine`/`PnLEngine`/
`AlertDeliveryService`/`InspectionJob`/`InspectionScheduler`/
`ReconciliationService`/`CompositeNotificationChannel`/ningún
transporte de notificación -- ver TestIsolation en el archivo de
pruebas, que audita las importaciones mediante `ast`, no búsqueda
textual.

Garantías:
- Nunca crea el archivo de base de datos ni ninguna tabla (`init()` no
  se llama en ningún camino de código; la conexión `mode=ro` de SQLite
  además lo impediría estructuralmente si se intentara).
- Nunca ejecuta INSERT/UPDATE/DELETE/ALTER/CREATE -- la conexión
  `mode=ro` los rechaza a nivel de SQLite (`sqlite3.OperationalError:
  attempt to write a readonly database`), no solo por convención de
  código.
- No requiere ninguna credencial de Telegram/Slack/Email/Webhook: no
  construye ningún transporte, no valida ningún secreto, no importa
  ningún `*_transport.py`.
- No inicia el scheduler, no reconcilia, no repara, no reintenta
  entregas, no genera inspecciones nuevas.
"""

import argparse
import json
import sqlite3
import sys
from decimal import Decimal
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from src.paper_trading.alert_models import AlertStatus, AlertType
from src.paper_trading.enums import OrderSource, OrderStatus
from src.paper_trading.reconciliation_models import IssueSeverity
from src.paper_trading.serialization import (
    optional_text_to_datetime, optional_text_to_decimal, text_to_datetime, text_to_decimal,
)

EXIT_OK = 0
EXIT_ARGUMENT_ERROR = 2
EXIT_CONFIG_ERROR = 3
EXIT_DATABASE_ERROR = 4
EXIT_QUERY_ERROR = 5

DEFAULT_LIMIT = 50
MAX_LIMIT = 1000

_NO_RECORDS_MESSAGE = "No records found."
_TABLE_MAX_TEXT_LENGTH = 80
_TABLE_TRUNCATION_MARK = "..."

# Las 11 tablas paper_trading_* que ya crea SQLitePaperTradingRepository.init()
# (Etapas 6.3/6.7/6.8/6.9/6.10.1) -- lista usada únicamente para distinguir
# "no existe ningún schema de Paper Trading todavía" de "existe pero está
# vacío". Esta CLI nunca las crea: solo las consulta si ya existen.
_REQUIRED_TABLES = (
    "paper_trading_cash_balances",
    "paper_trading_positions",
    "paper_trading_orders",
    "paper_trading_executions",
    "paper_trading_trades",
    "paper_trading_portfolio_snapshots",
    "paper_trading_pnl_snapshots",
    "paper_trading_inspection_runs",
    "paper_trading_inspection_alerts",
    "paper_trading_inspection_alert_channel_deliveries",
    "paper_trading_reconciliation_audit",
)


class PortfolioCliError(Exception):
    """Error controlado de consulta (código de salida 5). Nunca incluye
    SQL, rutas completas, ni credenciales en su mensaje."""


class DatabaseNotAvailableError(Exception):
    """La base no existe, no es un archivo válido, o no tiene el schema
    de Paper Trading esperado (código de salida 4)."""


class ConfigurationError(Exception):
    """No se pudo determinar/leer la configuración necesaria para
    resolver la ruta de la base de datos (código de salida 3)."""


# --------------------------------------------------------------------------
# Resolución de configuración y apertura read-only
# --------------------------------------------------------------------------

def _resolve_database_path(explicit_path: Optional[str]) -> str:
    """Si `--database-path` se recibió explícitamente, se usa tal cual
    (nunca se llama a load_settings()). Si se omitió, se reutiliza
    `paper_trading.database_path` de la configuración existente -- la
    misma que usa el resto del proyecto, sin un sistema de
    configuración alternativo."""
    if explicit_path is not None:
        return explicit_path

    from src.utils.config import load_settings  # import perezoso: evita cargarlo si no hace falta

    try:
        settings = load_settings()
    except Exception:
        raise ConfigurationError(
            "Could not load configuration to resolve the database path; pass --database-path explicitly."
        ) from None
    return settings.paper_trading.database_path


def _open_readonly_connection(database_path: str) -> sqlite3.Connection:
    """Abre `database_path` en modo real de solo lectura de SQLite
    (`mode=ro`): nunca crea el archivo si no existe, nunca crea
    tablas, y rechaza cualquier escritura a nivel del propio motor
    SQLite (no solo por convención de código)."""
    path = Path(database_path)

    if path.is_dir():
        raise DatabaseNotAvailableError("Database path points to a directory, not a file.")
    if not path.exists():
        raise DatabaseNotAvailableError("Database file does not exist.")

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        raise DatabaseNotAvailableError("Database file could not be opened in read-only mode.") from None

    try:
        existing_tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    except sqlite3.OperationalError:
        conn.close()
        raise DatabaseNotAvailableError("Database file could not be read.") from None

    missing = [table for table in _REQUIRED_TABLES if table not in existing_tables]
    if missing:
        conn.close()
        raise DatabaseNotAvailableError("Database does not have the expected Paper Trading schema yet.")

    return conn


# --------------------------------------------------------------------------
# Consultas (SQL propio, de solo lectura; nunca reutiliza motores/servicios)
# --------------------------------------------------------------------------

def _fetch_cash_balances(conn: sqlite3.Connection, *, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT currency, total_balance, reserved_balance, updated_at "
        "FROM paper_trading_cash_balances ORDER BY currency ASC LIMIT ?",
        (limit,),
    ).fetchall()
    result = []
    for currency, total_balance_text, reserved_balance_text, updated_at in rows:
        total_balance = text_to_decimal(total_balance_text)
        reserved_balance = text_to_decimal(reserved_balance_text)
        result.append({
            "currency": currency,
            "total_balance": total_balance,
            "reserved_balance": reserved_balance,
            "available_balance": total_balance - reserved_balance,
            "updated_at": text_to_datetime(updated_at),
        })
    return result


def _fetch_positions(
    conn: sqlite3.Connection, *, exchange: Optional[str], symbol: Optional[str], status: str, limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if exchange is not None:
        conditions.append("exchange = ?")
        params.append(exchange)
    if symbol is not None:
        conditions.append("symbol = ?")
        params.append(symbol)
    if status == "open":
        conditions.append("side != ?")
        params.append("FLAT")
    elif status == "flat":
        conditions.append("side = ?")
        params.append("FLAT")
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT exchange, symbol, side, quantity, reserved_quantity, average_entry_price, "
        f"realized_pnl_to_date, opened_at, updated_at FROM paper_trading_positions "
        f"{where_sql} ORDER BY exchange ASC, symbol ASC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "exchange": row[0], "symbol": row[1], "side": row[2],
            "quantity": text_to_decimal(row[3]), "reserved_quantity": text_to_decimal(row[4]),
            "average_entry_price": optional_text_to_decimal(row[5]),
            "realized_pnl_to_date": text_to_decimal(row[6]),
            "opened_at": optional_text_to_datetime(row[7]), "updated_at": text_to_datetime(row[8]),
        }
        for row in rows
    ]


def _fetch_orders(
    conn: sqlite3.Connection, *,
    exchange: Optional[str], symbol: Optional[str], status: Optional[str], source: Optional[str], limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if exchange is not None:
        conditions.append("exchange = ?")
        params.append(exchange)
    if symbol is not None:
        conditions.append("symbol = ?")
        params.append(symbol)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if source is not None:
        conditions.append("source = ?")
        params.append(source)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT id, exchange, symbol, side, order_type, quantity, filled_quantity, status, source, "
        f"created_at, updated_at, reserved_price, reserved_notional, reserved_fee, reserved_quantity "
        f"FROM paper_trading_orders {where_sql} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": row[0], "exchange": row[1], "symbol": row[2], "side": row[3], "order_type": row[4],
            "quantity": text_to_decimal(row[5]), "filled_quantity": text_to_decimal(row[6]),
            "status": row[7], "source": row[8],
            "created_at": text_to_datetime(row[9]), "updated_at": text_to_datetime(row[10]),
            "reserved_price": optional_text_to_decimal(row[11]),
            "reserved_notional": optional_text_to_decimal(row[12]),
            "reserved_fee": optional_text_to_decimal(row[13]),
            "reserved_quantity": optional_text_to_decimal(row[14]),
        }
        for row in rows
    ]


def _fetch_executions(
    conn: sqlite3.Connection, *,
    order_id: Optional[str], exchange: Optional[str], symbol: Optional[str], limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if order_id is not None:
        conditions.append("order_id = ?")
        params.append(order_id)
    if exchange is not None:
        conditions.append("exchange = ?")
        params.append(exchange)
    if symbol is not None:
        conditions.append("symbol = ?")
        params.append(symbol)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT id, order_id, exchange, symbol, quantity, price, fee, executed_at "
        f"FROM paper_trading_executions {where_sql} ORDER BY executed_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": row[0], "order_id": row[1], "exchange": row[2], "symbol": row[3],
            "quantity": text_to_decimal(row[4]), "price": text_to_decimal(row[5]),
            "fee": text_to_decimal(row[6]), "executed_at": text_to_datetime(row[7]),
        }
        for row in rows
    ]


def _fetch_trades(
    conn: sqlite3.Connection, *, exchange: Optional[str], symbol: Optional[str], limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if exchange is not None:
        conditions.append("exchange = ?")
        params.append(exchange)
    if symbol is not None:
        conditions.append("symbol = ?")
        params.append(symbol)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT id, exchange, symbol, side, quantity, entry_price, exit_price, gross_pnl, fees, "
        f"net_pnl, opened_at, closed_at FROM paper_trading_trades "
        f"{where_sql} ORDER BY closed_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": row[0], "exchange": row[1], "symbol": row[2], "side": row[3],
            "quantity": text_to_decimal(row[4]), "entry_price": text_to_decimal(row[5]),
            "exit_price": text_to_decimal(row[6]), "gross_pnl": text_to_decimal(row[7]),
            "fees": text_to_decimal(row[8]), "net_pnl": text_to_decimal(row[9]),
            "opened_at": text_to_datetime(row[10]), "closed_at": text_to_datetime(row[11]),
        }
        for row in rows
    ]


def _fetch_portfolio_snapshots(conn: sqlite3.Connection, *, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, cash_balance, positions_value, total_equity, "
        "unrealized_pnl_total, realized_pnl_cumulative FROM paper_trading_portfolio_snapshots "
        "ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row[0], "timestamp": text_to_datetime(row[1]), "cash_balance": text_to_decimal(row[2]),
            "positions_value": text_to_decimal(row[3]), "total_equity": text_to_decimal(row[4]),
            "unrealized_pnl_total": text_to_decimal(row[5]), "realized_pnl_cumulative": text_to_decimal(row[6]),
        }
        for row in rows
    ]


def _fetch_pnl_snapshots(conn: sqlite3.Connection, *, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, exchange, symbol, position_quantity, unrealized_pnl, "
        "realized_pnl_cumulative FROM paper_trading_pnl_snapshots ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row[0], "timestamp": text_to_datetime(row[1]), "exchange": row[2], "symbol": row[3],
            "position_quantity": text_to_decimal(row[4]), "unrealized_pnl": text_to_decimal(row[5]),
            "realized_pnl_cumulative": text_to_decimal(row[6]),
        }
        for row in rows
    ]


def _fetch_inspections(conn: sqlite3.Connection, *, status: Optional[str], limit: int) -> list[dict]:
    conditions = []
    params: list = []
    if status is not None:
        conditions.append("success = ?")
        params.append(1 if status == "success" else 0)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT id, success, started_at, completed_at, issue_count, alert_count, error_message "
        f"FROM paper_trading_inspection_runs {where_sql} ORDER BY started_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "run_id": row[0], "status": "success" if row[1] else "failed",
            "started_at": text_to_datetime(row[2]), "finished_at": text_to_datetime(row[3]),
            "issue_count": row[4], "alert_count": row[5], "error_message": row[6],
        }
        for row in rows
    ]


def _fetch_alerts(
    conn: sqlite3.Connection, *,
    status: Optional[str], alert_type: Optional[str], severity: Optional[str], limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if alert_type is not None:
        conditions.append("alert_type = ?")
        params.append(alert_type)
    if severity is not None:
        conditions.append("severity = ?")
        params.append(severity)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT id, deduplication_key, alert_type, severity, status, delivery_attempts, "
        f"created_at, delivered_at, last_error FROM paper_trading_inspection_alerts "
        f"{where_sql} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": row[0], "deduplication_key": row[1], "type": row[2], "severity": row[3], "status": row[4],
            "delivery_attempts": row[5], "created_at": text_to_datetime(row[6]),
            "delivered_at": optional_text_to_datetime(row[7]), "last_error": row[8],
        }
        for row in rows
    ]


def _fetch_deliveries(
    conn: sqlite3.Connection, *,
    alert_id: Optional[str], status: Optional[str], channel: Optional[str], limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if alert_id is not None:
        conditions.append("alert_id = ?")
        params.append(alert_id)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if channel is not None:
        conditions.append("channel_name = ?")
        params.append(channel)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT alert_id, channel_name, status, delivery_attempts, last_error, delivered_at, updated_at "
        f"FROM paper_trading_inspection_alert_channel_deliveries {where_sql} "
        f"ORDER BY updated_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "alert_id": row[0], "channel_name": row[1], "status": row[2], "delivery_attempts": row[3],
            "last_error": row[4], "delivered_at": optional_text_to_datetime(row[5]),
            "updated_at": text_to_datetime(row[6]),
        }
        for row in rows
    ]


def _fetch_reconciliation_audits(
    conn: sqlite3.Connection, *, run_id: Optional[str], status: Optional[str], limit: int,
) -> list[dict]:
    conditions = []
    params: list = []
    if run_id is not None:
        conditions.append("id = ?")
        params.append(run_id)
    if status is not None:
        conditions.append("success = ?")
        params.append(1 if status == "success" else 0)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"SELECT id, started_at, completed_at, dry_run, success, issue_count, repaired_count, "
        f"error_message FROM paper_trading_reconciliation_audit {where_sql} "
        f"ORDER BY started_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [
        {
            "id": row[0], "started_at": text_to_datetime(row[1]), "completed_at": text_to_datetime(row[2]),
            "dry_run": bool(row[3]), "success": bool(row[4]), "issue_count": row[5],
            "repaired_count": row[6], "error_message": row[7],
        }
        for row in rows
    ]


def _fetch_summary(conn: sqlite3.Connection, *, currency: str) -> dict:
    """No recalcula ninguna regla financiera: lee el último
    PortfolioSnapshot ya calculado por PnLEngine (Etapa 6.2) y
    persistido por PaperTradingService -- nunca recompone
    positions_value/total_equity/PnL desde cero."""
    cash_row = conn.execute(
        "SELECT total_balance, reserved_balance FROM paper_trading_cash_balances WHERE currency = ?",
        (currency,),
    ).fetchone()
    total_balance = text_to_decimal(cash_row[0]) if cash_row else None
    reserved_balance = text_to_decimal(cash_row[1]) if cash_row else None
    available_balance = (total_balance - reserved_balance) if cash_row else None

    snapshot_row = conn.execute(
        "SELECT timestamp, positions_value, total_equity, unrealized_pnl_total, realized_pnl_cumulative "
        "FROM paper_trading_portfolio_snapshots ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    open_positions_count = conn.execute(
        "SELECT COUNT(*) FROM paper_trading_positions WHERE side != 'FLAT'"
    ).fetchone()[0]
    pending_orders_count = conn.execute(
        "SELECT COUNT(*) FROM paper_trading_orders WHERE status = 'PENDING'"
    ).fetchone()[0]

    inspection_row = conn.execute(
        "SELECT started_at, completed_at, success FROM paper_trading_inspection_runs "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    pending_alerts_count = conn.execute(
        "SELECT COUNT(*) FROM paper_trading_inspection_alerts WHERE status = 'PENDING'"
    ).fetchone()[0]
    failed_alerts_count = conn.execute(
        "SELECT COUNT(*) FROM paper_trading_inspection_alerts WHERE status = 'FAILED'"
    ).fetchone()[0]

    return {
        "currency": currency,
        "total_balance": total_balance,
        "reserved_balance": reserved_balance,
        "available_balance": available_balance,
        "positions_value": text_to_decimal(snapshot_row[1]) if snapshot_row else None,
        "total_equity": text_to_decimal(snapshot_row[2]) if snapshot_row else None,
        "realized_pnl_cumulative": text_to_decimal(snapshot_row[4]) if snapshot_row else None,
        "unrealized_pnl_total": text_to_decimal(snapshot_row[3]) if snapshot_row else None,
        "open_positions_count": open_positions_count,
        "pending_orders_count": pending_orders_count,
        "last_snapshot_at": text_to_datetime(snapshot_row[0]) if snapshot_row else None,
        "last_inspection_started_at": text_to_datetime(inspection_row[0]) if inspection_row else None,
        "last_inspection_success": bool(inspection_row[2]) if inspection_row else None,
        "pending_alerts_count": pending_alerts_count,
        "failed_alerts_count": failed_alerts_count,
    }


# --------------------------------------------------------------------------
# Formato de salida (solo biblioteca estándar: sin tabulate/rich/pandas)
# --------------------------------------------------------------------------

def _truncate_text(text: str) -> str:
    if len(text) <= _TABLE_MAX_TEXT_LENGTH:
        return text
    return text[: _TABLE_MAX_TEXT_LENGTH - len(_TABLE_TRUNCATION_MARK)] + _TABLE_TRUNCATION_MARK


def _format_value_for_table(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return _truncate_text(str(value.value))
    return _truncate_text(str(value))


def render_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return _NO_RECORDS_MESSAGE

    formatted_rows = [[_format_value_for_table(row.get(column)) for column in columns] for row in rows]
    widths = [
        max(len(column), *(len(cell[i]) for cell in formatted_rows))
        for i, column in enumerate(columns)
    ]

    lines = ["  ".join(column.ljust(widths[i]) for i, column in enumerate(columns))]
    lines.append("  ".join("-" * widths[i] for i in range(len(columns))))
    for formatted_row in formatted_rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(formatted_row)))
    return "\n".join(lines)


def render_key_value(record: dict) -> str:
    """Formato de tabla para un único registro (ej. `summary`): más
    legible que una tabla de una sola fila con muchas columnas."""
    lines = []
    for key, value in record.items():
        lines.append(f"{key}: {_format_value_for_table(value)}")
    return "\n".join(lines)


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def render_json(data: Any) -> str:
    return json.dumps(data, default=_json_default, indent=2)


# --------------------------------------------------------------------------
# Validación de argumentos
# --------------------------------------------------------------------------

def _limit_type(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--limit must be an integer, got {value!r}.") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--limit must be a positive integer.")
    if parsed > MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"--limit must be at most {MAX_LIMIT}.")
    return parsed


def _enum_choice_type(enum_cls: type, flag_name: str) -> Callable[[str], str]:
    def _validate(value: str) -> str:
        try:
            return enum_cls(value).value
        except ValueError:
            valid = ", ".join(member.value for member in enum_cls)
            raise argparse.ArgumentTypeError(f"{flag_name} must be one of: {valid}") from None
    return _validate


def _add_limit_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=_limit_type, default=DEFAULT_LIMIT, help=f"Default {DEFAULT_LIMIT}, max {MAX_LIMIT}.")


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------

def _build_common_parser() -> argparse.ArgumentParser:
    """Argumentos globales (`--database-path`/`--format`), compartidos
    entre el parser raíz y cada uno de los once subparsers (Etapa
    6.18.1, §5/§6): permite que ambos se acepten tanto antes como
    después del subcomando.

    `argument_default=argparse.SUPPRESS`: ningún atributo se agrega al
    Namespace si el usuario no proporcionó el argumento -- ni aquí ni
    en el subparser. Esto evita que el default del subparser
    sobrescriba silenciosamente un valor ya reconocido por el parser
    raíz (§7); los defaults reales (`table`/`None`) se aplican una
    sola vez, después de `parse_args()`, con `getattr(args, ..., default)`.
    """
    parser = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    parser.add_argument(
        "--database-path", dest="database_path",
        help="Ruta al archivo SQLite. Si se omite, se reutiliza paper_trading.database_path de la configuración.",
    )
    parser.add_argument(
        "--format", dest="format", choices=["table", "json"],
        help="Formato de salida (default: table).",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    common_parser = _build_common_parser()

    parser = argparse.ArgumentParser(
        prog="python -m src.paper_trading.portfolio_cli",
        description="CLI operativa y estrictamente de solo lectura para consultar el estado de Paper Trading.",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "summary", parents=[common_parser], help="Resumen general de la cuenta (solo lectura).",
    )

    balances_parser = subparsers.add_parser(
        "balances", parents=[common_parser], help="Balances de efectivo por moneda.",
    )
    _add_limit_argument(balances_parser)

    positions_parser = subparsers.add_parser("positions", parents=[common_parser], help="Posiciones actuales.")
    positions_parser.add_argument("--exchange", default=None)
    positions_parser.add_argument("--symbol", default=None)
    positions_parser.add_argument("--status", choices=["open", "flat", "all"], default="all")
    _add_limit_argument(positions_parser)

    orders_parser = subparsers.add_parser("orders", parents=[common_parser], help="Órdenes.")
    orders_parser.add_argument("--exchange", default=None)
    orders_parser.add_argument("--symbol", default=None)
    orders_parser.add_argument("--status", type=_enum_choice_type(OrderStatus, "--status"), default=None)
    orders_parser.add_argument("--source", type=_enum_choice_type(OrderSource, "--source"), default=None)
    _add_limit_argument(orders_parser)

    executions_parser = subparsers.add_parser("executions", parents=[common_parser], help="Ejecuciones (fills).")
    executions_parser.add_argument("--order-id", dest="order_id", default=None)
    executions_parser.add_argument("--exchange", default=None)
    executions_parser.add_argument("--symbol", default=None)
    _add_limit_argument(executions_parser)

    trades_parser = subparsers.add_parser("trades", parents=[common_parser], help="Trades cerrados.")
    trades_parser.add_argument("--exchange", default=None)
    trades_parser.add_argument("--symbol", default=None)
    _add_limit_argument(trades_parser)

    snapshots_parser = subparsers.add_parser(
        "snapshots", parents=[common_parser], help="Snapshots de cartera o de PnL.",
    )
    snapshots_parser.add_argument("--type", dest="snapshot_type", choices=["portfolio", "pnl"], required=True)
    _add_limit_argument(snapshots_parser)

    inspections_parser = subparsers.add_parser(
        "inspections", parents=[common_parser], help="Corridas de inspección.",
    )
    inspections_parser.add_argument("--status", choices=["success", "failed"], default=None)
    _add_limit_argument(inspections_parser)

    alerts_parser = subparsers.add_parser("alerts", parents=[common_parser], help="Alertas de inspección.")
    alerts_parser.add_argument("--status", type=_enum_choice_type(AlertStatus, "--status"), default=None)
    alerts_parser.add_argument("--type", dest="alert_type", type=_enum_choice_type(AlertType, "--type"), default=None)
    alerts_parser.add_argument(
        "--severity", type=_enum_choice_type(IssueSeverity, "--severity"), default=None,
    )
    _add_limit_argument(alerts_parser)

    deliveries_parser = subparsers.add_parser(
        "deliveries", parents=[common_parser], help="Estado de entrega por canal.",
    )
    deliveries_parser.add_argument("--alert-id", dest="alert_id", default=None)
    deliveries_parser.add_argument("--status", type=_enum_choice_type(AlertStatus, "--status"), default=None)
    deliveries_parser.add_argument("--channel", default=None)
    _add_limit_argument(deliveries_parser)

    audits_parser = subparsers.add_parser(
        "reconciliation-audits", parents=[common_parser], help="Auditorías de reconciliación.",
    )
    audits_parser.add_argument("--run-id", dest="run_id", default=None)
    audits_parser.add_argument("--status", choices=["success", "failure"], default=None)
    _add_limit_argument(audits_parser)

    return parser


_COLLECTION_COLUMNS: dict[str, list[str]] = {
    "balances": ["currency", "total_balance", "reserved_balance", "available_balance", "updated_at"],
    "positions": [
        "exchange", "symbol", "side", "quantity", "reserved_quantity",
        "average_entry_price", "realized_pnl_to_date", "opened_at", "updated_at",
    ],
    "orders": [
        "id", "exchange", "symbol", "side", "order_type", "quantity", "filled_quantity",
        "status", "source", "created_at", "updated_at",
    ],
    "executions": ["id", "order_id", "exchange", "symbol", "quantity", "price", "fee", "executed_at"],
    "trades": [
        "id", "exchange", "symbol", "side", "quantity", "entry_price", "exit_price",
        "gross_pnl", "fees", "net_pnl", "opened_at", "closed_at",
    ],
    "portfolio_snapshots": [
        "id", "timestamp", "cash_balance", "positions_value", "total_equity",
        "unrealized_pnl_total", "realized_pnl_cumulative",
    ],
    "pnl_snapshots": [
        "id", "timestamp", "exchange", "symbol", "position_quantity", "unrealized_pnl", "realized_pnl_cumulative",
    ],
    "inspections": ["run_id", "status", "started_at", "finished_at", "issue_count", "alert_count", "error_message"],
    "alerts": [
        "id", "deduplication_key", "type", "severity", "status", "delivery_attempts",
        "created_at", "delivered_at", "last_error",
    ],
    "deliveries": [
        "alert_id", "channel_name", "status", "delivery_attempts", "last_error", "delivered_at", "updated_at",
    ],
    "reconciliation-audits": [
        "id", "started_at", "completed_at", "dry_run", "success", "issue_count", "repaired_count", "error_message",
    ],
}


def _run_command(conn: sqlite3.Connection, args: argparse.Namespace) -> Any:
    if args.command == "summary":
        return _fetch_summary(conn, currency="USDT")
    if args.command == "balances":
        return _fetch_cash_balances(conn, limit=args.limit)
    if args.command == "positions":
        return _fetch_positions(
            conn, exchange=args.exchange, symbol=args.symbol, status=args.status, limit=args.limit,
        )
    if args.command == "orders":
        return _fetch_orders(
            conn, exchange=args.exchange, symbol=args.symbol, status=args.status,
            source=args.source, limit=args.limit,
        )
    if args.command == "executions":
        return _fetch_executions(
            conn, order_id=args.order_id, exchange=args.exchange, symbol=args.symbol, limit=args.limit,
        )
    if args.command == "trades":
        return _fetch_trades(conn, exchange=args.exchange, symbol=args.symbol, limit=args.limit)
    if args.command == "snapshots":
        if args.snapshot_type == "portfolio":
            return _fetch_portfolio_snapshots(conn, limit=args.limit)
        return _fetch_pnl_snapshots(conn, limit=args.limit)
    if args.command == "inspections":
        return _fetch_inspections(conn, status=args.status, limit=args.limit)
    if args.command == "alerts":
        return _fetch_alerts(
            conn, status=args.status, alert_type=args.alert_type, severity=args.severity, limit=args.limit,
        )
    if args.command == "deliveries":
        return _fetch_deliveries(
            conn, alert_id=args.alert_id, status=args.status, channel=args.channel, limit=args.limit,
        )
    if args.command == "reconciliation-audits":
        return _fetch_reconciliation_audits(conn, run_id=args.run_id, status=args.status, limit=args.limit)
    raise AssertionError(f"unreachable command: {args.command!r}")  # pragma: no cover


def _columns_for(args: argparse.Namespace) -> list[str]:
    if args.command == "snapshots":
        return _COLLECTION_COLUMNS["portfolio_snapshots" if args.snapshot_type == "portfolio" else "pnl_snapshots"]
    return _COLLECTION_COLUMNS[args.command]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Etapa 6.18.1 (§7): --database-path/--format usan argument_default=SUPPRESS
    # en el parser compartido (ver _build_common_parser()) para que el
    # default del subparser nunca sobrescriba un valor ya reconocido por
    # el parser raíz (o viceversa) -- el atributo puede estar
    # directamente ausente del Namespace si el usuario nunca lo dio, ni
    # antes ni después del subcomando. Los defaults reales se aplican
    # aquí, una sola vez, después de parse_args().
    explicit_database_path = getattr(args, "database_path", None)
    output_format = getattr(args, "format", "table")

    try:
        database_path = _resolve_database_path(explicit_database_path)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG_ERROR

    try:
        conn = _open_readonly_connection(database_path)
    except DatabaseNotAvailableError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DATABASE_ERROR

    try:
        try:
            result = _run_command(conn, args)
        except PortfolioCliError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_QUERY_ERROR
        except sqlite3.Error:
            print("Query failed unexpectedly.", file=sys.stderr)
            return EXIT_QUERY_ERROR
    finally:
        conn.close()

    if output_format == "json":
        print(render_json(result))
    elif args.command == "summary":
        print(render_key_value(result))
    else:
        print(render_table(result, _columns_for(args)))

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
