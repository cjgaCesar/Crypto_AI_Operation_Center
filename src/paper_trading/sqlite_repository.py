"""
Implementación de PaperTradingRepository usando SQLite (Etapa 6.3).

Guarda el dominio de Paper Trading en 7 tablas nuevas e independientes,
todas con el prefijo `paper_trading_`, sin modificar `market_data`,
`market_indicators`, `market_signals` ni `ai_recommendations`. Sigue el
mismo patrón de conexión que el resto del proyecto (una conexión nueva
por llamada, `try/finally: conn.close()`, `CREATE TABLE IF NOT EXISTS`
+ `PRAGMA table_info` para migraciones aditivas) — ver
src/ai/sqlite_repository.py y src/signals/sqlite_repository.py.

Decisiones de esta etapa (documentadas también en
docs/ARQUITECTURA_PAPER_TRADING.md):

- **Decimal como TEXT.** Todo campo monetario/cantidad/PnL se guarda
  como `str(value)` y se reconstruye con `Decimal(value)` (ver
  serialization.py) -- nunca `REAL`, que perdería precisión al
  convertir a binario de punto flotante.
- **INSERT vs UPSERT.** `Execution`, `Trade`, `PortfolioSnapshot` y
  `PnLSnapshot` son históricos e inmutables: se insertan, nunca se
  actualizan ni se reemplazan (`INSERT` simple, sin `OR REPLACE` ni
  `OR IGNORE` -- una colisión de clave primaria debe fallar de forma
  ruidosa, nunca ocultarse). `Order`, `Position` y `CashBalance` son
  estado actual: usan `INSERT ... ON CONFLICT DO UPDATE` (upsert
  explícito de SQLite), preservando su identidad (`Order.created_at`
  nunca se sobrescribe en un upsert).
- **`save_fill_transaction` es la única operación multi-tabla.** Abre
  una única conexión, ejecuta los helpers privados `_upsert_*`/
  `_insert_*` (que reciben la conexión ya abierta, sin abrir la suya
  propia) en el orden Order -> Execution -> Position -> CashBalance ->
  Trade -> PortfolioSnapshot -> PnLSnapshot, y hace un único `commit()`
  al final. Cualquier excepción dispara `rollback()` antes de
  relanzarla: no puede quedar un estado parcial. Los métodos públicos
  `save_order`/`save_execution`/etc. usan los mismos helpers privados,
  pero cada uno abre y cierra su propia conexión (para poder usarse de
  forma independiente fuera de una transacción de fill).
- **Fuente de verdad del PnL realizado.** `paper_trading_trades` es la
  fuente primaria histórica; `Position.realized_pnl_to_date` es un
  estado materializado para lectura rápida (lo mantiene el motor,
  Etapa 6.2). `calculate_realized_pnl()` sólo lee `net_pnl` como TEXT y
  suma con `Decimal` en Python (nunca `SUM(net_pnl)` en SQL: SQLite
  convertiría la columna TEXT a `REAL` y perdería precisión).
  `check_position_pnl_consistency()` compara ambas fuentes sin
  modificar ninguna -- la reconciliación real (si alguna vez difieren)
  es decisión de un futuro Service (Etapa 6.4), no de este repositorio.

Etapa 6.17 (§32, concurrencia y contención SQLite): antes de esta etapa,
`_get_connection()` llamaba `sqlite3.connect(path)` sin `timeout=`
explícito -- Python ya aplicaba su propio default (5.0 segundos,
equivalente a `PRAGMA busy_timeout = 5000`), pero de forma implícita,
no configurable ni verificada por ninguna prueba. Se caracterizó el
comportamiento real (dos conexiones, una con `BEGIN IMMEDIATE` sin
commit, la otra escribiendo) antes de modificar nada: la segunda
escritura espera el tiempo del timeout y falla de forma controlada
(`sqlite3.OperationalError: database is locked`), sin cuelgue, sin
corrupción -- ver tests/test_paper_trading_sqlite_concurrency.py. El
cambio aplicado es mínimo: `timeout_seconds` pasa a ser un parámetro
explícito del constructor (mismo valor por defecto, 5.0, para no
alterar el comportamiento ya vigente), validado, y propagado a
`sqlite3.connect(..., timeout=timeout_seconds)`. `PRAGMA journal_mode`
se mide (queda en `delete`, el modo por defecto) pero **no se activa
WAL**: no se demostró un problema real que WAL resolviera para el
patrón de uso actual (conexión nueva y transacción corta por
operación) -- ver la sección 32 de docs/ARQUITECTURA_PAPER_TRADING.md
para el detalle completo de la evidencia y la decisión.
"""

import math
from pathlib import Path
import sqlite3
from decimal import Decimal
from typing import Optional

DEFAULT_SQLITE_TIMEOUT_SECONDS = 5.0

from src.paper_trading.alert_models import AlertStatus, InspectionAlert, InspectionAlertChannelDelivery
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderStatus, PositionSide
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.models import (
    CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade,
)
from src.paper_trading.reconciliation_models import ReconciliationAuditRecord
from src.paper_trading.serialization import (
    datetime_to_text, decimal_to_text, deserialize_inspection_alert, deserialize_inspection_run,
    optional_datetime_to_text, optional_decimal_to_text, optional_text_to_datetime, optional_text_to_decimal,
    serialize_inspection_alert, serialize_inspection_run, text_to_datetime, text_to_decimal,
)

_ORDER_COLUMNS = (
    "id", "exchange", "symbol", "side", "order_type", "quantity", "limit_price", "status",
    "filled_quantity", "average_fill_price", "source", "linked_recommendation_id",
    "rejection_reason", "cancellation_reason", "created_at", "updated_at", "expires_at",
    "reserved_price", "reserved_notional", "reserved_fee", "reserved_quantity",
)

# Columnas agregadas después de la primera versión de paper_trading_orders
# (Etapa 6.7, ver ARQUITECTURA_PAPER_TRADING.md §21.2), con la definición
# SQL a usar en ALTER TABLE ... ADD COLUMN -- mismo patrón idempotente ya
# usado por SQLiteSignalRepository/SQLiteAIRepository. Las 4 son
# nullable (sin NOT NULL): no tienen un valor por defecto razonable
# distinto de NULL para las filas ya existentes.
_ORDER_MIGRATION_COLUMNS = [
    ("reserved_price", "TEXT"),
    ("reserved_notional", "TEXT"),
    ("reserved_fee", "TEXT"),
    ("reserved_quantity", "TEXT"),
]
_EXECUTION_COLUMNS = ("id", "order_id", "exchange", "symbol", "quantity", "price", "fee", "executed_at")
_TRADE_COLUMNS = (
    "id", "exchange", "symbol", "side", "quantity", "entry_price", "exit_price",
    "gross_pnl", "fees", "net_pnl", "opened_at", "closed_at", "exit_execution_id",
)
_POSITION_COLUMNS = (
    "exchange", "symbol", "side", "quantity", "reserved_quantity",
    "average_entry_price", "realized_pnl_to_date", "opened_at", "updated_at",
)
_CASH_BALANCE_COLUMNS = ("currency", "total_balance", "reserved_balance", "updated_at")
_RECONCILIATION_AUDIT_COLUMNS = (
    "id", "started_at", "completed_at", "dry_run", "success",
    "issue_count", "repaired_count", "report_json", "operations_json", "error_message",
)
_INSPECTION_RUN_COLUMNS = (
    "id", "started_at", "completed_at", "success", "report_json", "issue_count", "critical_count",
    "error_count", "warning_count", "info_count", "previous_run_id", "new_issue_count",
    "resolved_issue_count", "persistent_issue_count", "changed_issue_count", "alert_count", "error_message",
)
_INSPECTION_ALERT_COLUMNS = (
    "id", "run_id", "alert_type", "issue_key", "issue_code", "severity", "title", "message",
    "deduplication_key", "status", "delivery_attempts", "last_error", "created_at", "delivered_at",
)
_ALERT_CHANNEL_DELIVERY_COLUMNS = (
    "alert_id", "channel_name", "status", "delivery_attempts", "last_error", "delivered_at", "updated_at",
)
_PORTFOLIO_SNAPSHOT_COLUMNS = (
    "id", "timestamp", "cash_balance", "positions_value",
    "total_equity", "unrealized_pnl_total", "realized_pnl_cumulative",
)
_PNL_SNAPSHOT_COLUMNS = (
    "id", "timestamp", "exchange", "symbol",
    "position_quantity", "unrealized_pnl", "realized_pnl_cumulative",
)


class SQLitePaperTradingRepository(PaperTradingRepository):
    def __init__(self, db_path: str, *, timeout_seconds: float = DEFAULT_SQLITE_TIMEOUT_SECONDS):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("SQLite timeout must be a finite number greater than zero.")
        self.db_path = db_path
        self._timeout_seconds = timeout_seconds

    def _get_connection(self) -> sqlite3.Connection:
        """Conexión nueva por operación (nunca compartida entre hilos, nunca
        un singleton): mismo patrón ya vigente desde la Etapa 6.3, ahora con
        `timeout=self._timeout_seconds` explícito -- antes de la Etapa
        6.17, este valor ya era 5.0s (default de Python), solo que
        implícito y no configurable. `PRAGMA foreign_keys = ON` se aplica
        aquí, en cada conexión nueva -- no solo en `init()` -- porque
        SQLite no conserva ese pragma entre conexiones distintas."""
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=self._timeout_seconds)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # --- init / migraciones -----------------------------------------------

    def init(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_orders (
                    id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    limit_price TEXT,
                    status TEXT NOT NULL,
                    filled_quantity TEXT NOT NULL,
                    average_fill_price TEXT,
                    source TEXT NOT NULL,
                    linked_recommendation_id TEXT,
                    rejection_reason TEXT,
                    cancellation_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_executions (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES paper_trading_orders(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_trades (
                    id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    entry_price TEXT NOT NULL,
                    exit_price TEXT NOT NULL,
                    gross_pnl TEXT NOT NULL,
                    fees TEXT NOT NULL,
                    net_pnl TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT NOT NULL,
                    exit_execution_id TEXT NOT NULL,
                    FOREIGN KEY(exit_execution_id) REFERENCES paper_trading_executions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_positions (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    reserved_quantity TEXT NOT NULL,
                    average_entry_price TEXT,
                    realized_pnl_to_date TEXT NOT NULL,
                    opened_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(exchange, symbol)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_cash_balances (
                    currency TEXT PRIMARY KEY,
                    total_balance TEXT NOT NULL,
                    reserved_balance TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cash_balance TEXT NOT NULL,
                    positions_value TEXT NOT NULL,
                    total_equity TEXT NOT NULL,
                    unrealized_pnl_total TEXT NOT NULL,
                    realized_pnl_cumulative TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_pnl_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    position_quantity TEXT NOT NULL,
                    unrealized_pnl TEXT NOT NULL,
                    realized_pnl_cumulative TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_reconciliation_audit (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    issue_count INTEGER NOT NULL,
                    repaired_count INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    operations_json TEXT NOT NULL,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_inspection_runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    report_json TEXT,
                    issue_count INTEGER NOT NULL,
                    critical_count INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    warning_count INTEGER NOT NULL,
                    info_count INTEGER NOT NULL,
                    previous_run_id TEXT,
                    new_issue_count INTEGER NOT NULL,
                    resolved_issue_count INTEGER NOT NULL,
                    persistent_issue_count INTEGER NOT NULL,
                    changed_issue_count INTEGER NOT NULL,
                    alert_count INTEGER NOT NULL,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_inspection_alerts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    issue_key TEXT,
                    issue_code TEXT,
                    severity TEXT,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    deduplication_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    delivery_attempts INTEGER NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    FOREIGN KEY(run_id) REFERENCES paper_trading_inspection_runs(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trading_inspection_alert_channel_deliveries (
                    alert_id TEXT NOT NULL,
                    channel_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    delivery_attempts INTEGER NOT NULL,
                    last_error TEXT,
                    delivered_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (alert_id, channel_name),
                    FOREIGN KEY(alert_id) REFERENCES paper_trading_inspection_alerts(id)
                )
                """
            )
            self._migrate_missing_columns(conn)
            self._create_indexes(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_missing_columns(conn: sqlite3.Connection) -> None:
        """Migra bases creadas antes de la Etapa 6.7 (sin las 4 columnas
        de reserva en paper_trading_orders), sin perder ni alterar ningún
        registro existente. Idempotente: si ya se ejecutó antes (las
        columnas ya existen), no hace nada."""
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_trading_orders)")}
        for column, definition in _ORDER_MIGRATION_COLUMNS:
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE paper_trading_orders ADD COLUMN {column} {definition}")

    @staticmethod
    def _create_indexes(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_orders_lookup "
            "ON paper_trading_orders(exchange, symbol, status, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_executions_order "
            "ON paper_trading_executions(order_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_executions_lookup "
            "ON paper_trading_executions(exchange, symbol, executed_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_trades_lookup "
            "ON paper_trading_trades(exchange, symbol, closed_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_portfolio_snapshots_timestamp "
            "ON paper_trading_portfolio_snapshots(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_pnl_snapshots_lookup "
            "ON paper_trading_pnl_snapshots(exchange, symbol, timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_reconciliation_audit_started_at "
            "ON paper_trading_reconciliation_audit(started_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_inspection_runs_started_at "
            "ON paper_trading_inspection_runs(started_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_inspection_alerts_run_id "
            "ON paper_trading_inspection_alerts(run_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_inspection_alerts_created_at "
            "ON paper_trading_inspection_alerts(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_trading_inspection_alerts_status "
            "ON paper_trading_inspection_alerts(status)"
        )
        # deduplication_key ya tiene un índice implícito por su UNIQUE
        # (SQLite crea uno automáticamente) -- no se duplica aquí.

    @staticmethod
    def _validate_limit(limit: Optional[int]) -> None:
        if limit is not None and limit <= 0:
            raise ValueError("limit debe ser un entero positivo, o None para no limitar.")

    # --- Order ------------------------------------------------------------

    def save_order(self, order: Order) -> None:
        conn = self._get_connection()
        try:
            self._upsert_order(conn, order)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _upsert_order(conn: sqlite3.Connection, order: Order) -> None:
        conn.execute(
            f"""
            INSERT INTO paper_trading_orders ({', '.join(_ORDER_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_ORDER_COLUMNS))})
            ON CONFLICT(id) DO UPDATE SET
                exchange=excluded.exchange, symbol=excluded.symbol, side=excluded.side,
                order_type=excluded.order_type, quantity=excluded.quantity,
                limit_price=excluded.limit_price, status=excluded.status,
                filled_quantity=excluded.filled_quantity,
                average_fill_price=excluded.average_fill_price, source=excluded.source,
                linked_recommendation_id=excluded.linked_recommendation_id,
                rejection_reason=excluded.rejection_reason,
                cancellation_reason=excluded.cancellation_reason,
                updated_at=excluded.updated_at, expires_at=excluded.expires_at,
                reserved_price=excluded.reserved_price, reserved_notional=excluded.reserved_notional,
                reserved_fee=excluded.reserved_fee, reserved_quantity=excluded.reserved_quantity
            """,
            (
                order.id, order.exchange, order.symbol, order.side.value, order.order_type.value,
                decimal_to_text(order.quantity), optional_decimal_to_text(order.limit_price),
                order.status.value, decimal_to_text(order.filled_quantity),
                optional_decimal_to_text(order.average_fill_price), order.source.value,
                order.linked_recommendation_id, order.rejection_reason, order.cancellation_reason,
                datetime_to_text(order.created_at), datetime_to_text(order.updated_at),
                optional_datetime_to_text(order.expires_at),
                optional_decimal_to_text(order.reserved_price), optional_decimal_to_text(order.reserved_notional),
                optional_decimal_to_text(order.reserved_fee), optional_decimal_to_text(order.reserved_quantity),
            ),
        )

    def get_order(self, order_id: str) -> Optional[Order]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_ORDER_COLUMNS)} FROM paper_trading_orders WHERE id = ?",
                (order_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_order(row) if row else None

    def fetch_orders(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        limit: Optional[int] = None,
    ) -> list[Order]:
        self._validate_limit(limit)
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
            params.append(status.value)
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_ORDER_COLUMNS)} FROM paper_trading_orders "
                f"{where_sql} ORDER BY created_at DESC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_order(row) for row in rows]

    @staticmethod
    def _row_to_order(row) -> Order:
        return Order(
            id=row[0], exchange=row[1], symbol=row[2], side=row[3], order_type=row[4],
            quantity=text_to_decimal(row[5]), limit_price=optional_text_to_decimal(row[6]),
            status=row[7], filled_quantity=text_to_decimal(row[8]),
            average_fill_price=optional_text_to_decimal(row[9]), source=row[10],
            linked_recommendation_id=row[11], rejection_reason=row[12], cancellation_reason=row[13],
            created_at=text_to_datetime(row[14]), updated_at=text_to_datetime(row[15]),
            expires_at=optional_text_to_datetime(row[16]),
            reserved_price=optional_text_to_decimal(row[17]), reserved_notional=optional_text_to_decimal(row[18]),
            reserved_fee=optional_text_to_decimal(row[19]), reserved_quantity=optional_text_to_decimal(row[20]),
        )

    # --- Execution ----------------------------------------------------------

    def save_execution(self, execution: Execution) -> None:
        conn = self._get_connection()
        try:
            self._insert_execution(conn, execution)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _insert_execution(conn: sqlite3.Connection, execution: Execution) -> None:
        conn.execute(
            f"""
            INSERT INTO paper_trading_executions ({', '.join(_EXECUTION_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_EXECUTION_COLUMNS))})
            """,
            (
                execution.id, execution.order_id, execution.exchange, execution.symbol,
                decimal_to_text(execution.quantity), decimal_to_text(execution.price),
                decimal_to_text(execution.fee), datetime_to_text(execution.executed_at),
            ),
        )

    def fetch_executions_by_order(self, order_id: str) -> list[Execution]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_EXECUTION_COLUMNS)} FROM paper_trading_executions "
                "WHERE order_id = ? ORDER BY executed_at ASC",
                (order_id,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_execution(row) for row in rows]

    def fetch_executions(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Execution]:
        self._validate_limit(limit)
        conditions = []
        params: list = []
        if exchange is not None:
            conditions.append("exchange = ?")
            params.append(exchange)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_EXECUTION_COLUMNS)} FROM paper_trading_executions "
                f"{where_sql} ORDER BY executed_at DESC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_execution(row) for row in rows]

    @staticmethod
    def _row_to_execution(row) -> Execution:
        return Execution(
            id=row[0], order_id=row[1], exchange=row[2], symbol=row[3],
            quantity=text_to_decimal(row[4]), price=text_to_decimal(row[5]),
            fee=text_to_decimal(row[6]), executed_at=text_to_datetime(row[7]),
        )

    # --- Trade --------------------------------------------------------------

    def save_trade(self, trade: Trade) -> None:
        conn = self._get_connection()
        try:
            self._insert_trade(conn, trade)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _insert_trade(conn: sqlite3.Connection, trade: Trade) -> None:
        conn.execute(
            f"""
            INSERT INTO paper_trading_trades ({', '.join(_TRADE_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_TRADE_COLUMNS))})
            """,
            (
                trade.id, trade.exchange, trade.symbol, trade.side.value,
                decimal_to_text(trade.quantity), decimal_to_text(trade.entry_price),
                decimal_to_text(trade.exit_price), decimal_to_text(trade.gross_pnl),
                decimal_to_text(trade.fees), decimal_to_text(trade.net_pnl),
                datetime_to_text(trade.opened_at), datetime_to_text(trade.closed_at),
                trade.exit_execution_id,
            ),
        )

    def fetch_trades(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Trade]:
        self._validate_limit(limit)
        conditions = []
        params: list = []
        if exchange is not None:
            conditions.append("exchange = ?")
            params.append(exchange)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_TRADE_COLUMNS)} FROM paper_trading_trades "
                f"{where_sql} ORDER BY closed_at DESC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_trade(row) for row in rows]

    @staticmethod
    def _row_to_trade(row) -> Trade:
        return Trade(
            id=row[0], exchange=row[1], symbol=row[2], side=row[3],
            quantity=text_to_decimal(row[4]), entry_price=text_to_decimal(row[5]),
            exit_price=text_to_decimal(row[6]), gross_pnl=text_to_decimal(row[7]),
            fees=text_to_decimal(row[8]), net_pnl=text_to_decimal(row[9]),
            opened_at=text_to_datetime(row[10]), closed_at=text_to_datetime(row[11]),
            exit_execution_id=row[12],
        )

    # --- Position -------------------------------------------------------

    def save_position(self, position: Position) -> None:
        conn = self._get_connection()
        try:
            self._upsert_position(conn, position)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _upsert_position(conn: sqlite3.Connection, position: Position) -> None:
        conn.execute(
            f"""
            INSERT INTO paper_trading_positions ({', '.join(_POSITION_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_POSITION_COLUMNS))})
            ON CONFLICT(exchange, symbol) DO UPDATE SET
                side=excluded.side, quantity=excluded.quantity,
                reserved_quantity=excluded.reserved_quantity,
                average_entry_price=excluded.average_entry_price,
                realized_pnl_to_date=excluded.realized_pnl_to_date,
                opened_at=excluded.opened_at, updated_at=excluded.updated_at
            """,
            (
                position.exchange, position.symbol, position.side.value,
                decimal_to_text(position.quantity), decimal_to_text(position.reserved_quantity),
                optional_decimal_to_text(position.average_entry_price),
                decimal_to_text(position.realized_pnl_to_date),
                optional_datetime_to_text(position.opened_at),
                datetime_to_text(position.updated_at),
            ),
        )

    def get_position(self, exchange: str, symbol: str) -> Optional[Position]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_POSITION_COLUMNS)} FROM paper_trading_positions "
                "WHERE exchange = ? AND symbol = ?",
                (exchange, symbol),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_position(row) if row else None

    def fetch_positions(self, include_flat: bool = True) -> list[Position]:
        conn = self._get_connection()
        try:
            if include_flat:
                cursor = conn.execute(
                    f"SELECT {', '.join(_POSITION_COLUMNS)} FROM paper_trading_positions "
                    "ORDER BY exchange ASC, symbol ASC"
                )
            else:
                cursor = conn.execute(
                    f"SELECT {', '.join(_POSITION_COLUMNS)} FROM paper_trading_positions "
                    "WHERE side != ? ORDER BY exchange ASC, symbol ASC",
                    (PositionSide.FLAT.value,),
                )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_position(row) for row in rows]

    @staticmethod
    def _row_to_position(row) -> Position:
        return Position(
            exchange=row[0], symbol=row[1], side=row[2], quantity=text_to_decimal(row[3]),
            reserved_quantity=text_to_decimal(row[4]),
            average_entry_price=optional_text_to_decimal(row[5]),
            realized_pnl_to_date=text_to_decimal(row[6]),
            opened_at=optional_text_to_datetime(row[7]), updated_at=text_to_datetime(row[8]),
        )

    # --- CashBalance ------------------------------------------------------

    def save_cash_balance(self, cash_balance: CashBalance) -> None:
        conn = self._get_connection()
        try:
            self._upsert_cash_balance(conn, cash_balance)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _upsert_cash_balance(conn: sqlite3.Connection, cash_balance: CashBalance) -> None:
        conn.execute(
            f"""
            INSERT INTO paper_trading_cash_balances ({', '.join(_CASH_BALANCE_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_CASH_BALANCE_COLUMNS))})
            ON CONFLICT(currency) DO UPDATE SET
                total_balance=excluded.total_balance, reserved_balance=excluded.reserved_balance,
                updated_at=excluded.updated_at
            """,
            (
                cash_balance.currency, decimal_to_text(cash_balance.total_balance),
                decimal_to_text(cash_balance.reserved_balance), datetime_to_text(cash_balance.updated_at),
            ),
        )

    def get_cash_balance(self, currency: str = "USDT") -> Optional[CashBalance]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_CASH_BALANCE_COLUMNS)} FROM paper_trading_cash_balances "
                "WHERE currency = ?",
                (currency,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_cash_balance(row) if row else None

    @staticmethod
    def _row_to_cash_balance(row) -> CashBalance:
        return CashBalance(
            currency=row[0], total_balance=text_to_decimal(row[1]),
            reserved_balance=text_to_decimal(row[2]), updated_at=text_to_datetime(row[3]),
        )

    def fetch_cash_balances(self) -> list[CashBalance]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_CASH_BALANCE_COLUMNS)} FROM paper_trading_cash_balances ORDER BY currency ASC"
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_cash_balance(row) for row in rows]

    # --- PortfolioSnapshot --------------------------------------------------

    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        conn = self._get_connection()
        try:
            self._insert_portfolio_snapshot(conn, snapshot)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _insert_portfolio_snapshot(conn: sqlite3.Connection, snapshot: PortfolioSnapshot) -> None:
        conn.execute(
            """
            INSERT INTO paper_trading_portfolio_snapshots
                (timestamp, cash_balance, positions_value, total_equity,
                 unrealized_pnl_total, realized_pnl_cumulative)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime_to_text(snapshot.timestamp), decimal_to_text(snapshot.cash_balance),
                decimal_to_text(snapshot.positions_value), decimal_to_text(snapshot.total_equity),
                decimal_to_text(snapshot.unrealized_pnl_total),
                decimal_to_text(snapshot.realized_pnl_cumulative),
            ),
        )

    def fetch_portfolio_history(self, limit: Optional[int] = None) -> list[PortfolioSnapshot]:
        self._validate_limit(limit)
        limit_sql = ""
        params: list = []
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_PORTFOLIO_SNAPSHOT_COLUMNS)} FROM paper_trading_portfolio_snapshots "
                f"ORDER BY timestamp DESC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_portfolio_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_portfolio_snapshot(row) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            id=row[0], timestamp=text_to_datetime(row[1]), cash_balance=text_to_decimal(row[2]),
            positions_value=text_to_decimal(row[3]), total_equity=text_to_decimal(row[4]),
            unrealized_pnl_total=text_to_decimal(row[5]), realized_pnl_cumulative=text_to_decimal(row[6]),
        )

    # --- PnLSnapshot ------------------------------------------------------

    def save_pnl_snapshot(self, snapshot: PnLSnapshot) -> None:
        conn = self._get_connection()
        try:
            self._insert_pnl_snapshot(conn, snapshot)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _insert_pnl_snapshot(conn: sqlite3.Connection, snapshot: PnLSnapshot) -> None:
        conn.execute(
            """
            INSERT INTO paper_trading_pnl_snapshots
                (timestamp, exchange, symbol, position_quantity, unrealized_pnl, realized_pnl_cumulative)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime_to_text(snapshot.timestamp), snapshot.exchange, snapshot.symbol,
                decimal_to_text(snapshot.position_quantity), decimal_to_text(snapshot.unrealized_pnl),
                decimal_to_text(snapshot.realized_pnl_cumulative),
            ),
        )

    def fetch_pnl_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None,
    ) -> list[PnLSnapshot]:
        self._validate_limit(limit)
        limit_sql = ""
        params: list = [exchange, symbol]
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_PNL_SNAPSHOT_COLUMNS)} FROM paper_trading_pnl_snapshots "
                f"WHERE exchange = ? AND symbol = ? ORDER BY timestamp DESC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_pnl_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_pnl_snapshot(row) -> PnLSnapshot:
        return PnLSnapshot(
            id=row[0], timestamp=text_to_datetime(row[1]), exchange=row[2], symbol=row[3],
            position_quantity=text_to_decimal(row[4]), unrealized_pnl=text_to_decimal(row[5]),
            realized_pnl_cumulative=text_to_decimal(row[6]),
        )

    # --- Transacción atómica de fill --------------------------------------

    def save_fill_transaction(
        self,
        order: Order,
        execution: Execution,
        position: Position,
        cash_balance: CashBalance,
        trade: Optional[Trade] = None,
        portfolio_snapshot: Optional[PortfolioSnapshot] = None,
        pnl_snapshot: Optional[PnLSnapshot] = None,
    ) -> None:
        self._validate_fill_consistency(order, execution, position, trade, pnl_snapshot)

        conn = self._get_connection()
        try:
            self._upsert_order(conn, order)
            self._insert_execution(conn, execution)
            self._upsert_position(conn, position)
            self._upsert_cash_balance(conn, cash_balance)
            if trade is not None:
                self._insert_trade(conn, trade)
            if portfolio_snapshot is not None:
                self._insert_portfolio_snapshot(conn, portfolio_snapshot)
            if pnl_snapshot is not None:
                self._insert_pnl_snapshot(conn, pnl_snapshot)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validate_fill_consistency(
        order: Order,
        execution: Execution,
        position: Position,
        trade: Optional[Trade],
        pnl_snapshot: Optional[PnLSnapshot],
    ) -> None:
        """Validaciones de consistencia relacional (Paso 15): no es lógica de
        negocio (no recalcula fee/PnL/cantidad), solo confirma que las
        entidades recibidas realmente pertenecen entre sí antes de escribir
        nada."""
        if execution.order_id != order.id:
            raise ValueError("execution.order_id no coincide con order.id.")
        if execution.exchange != order.exchange or execution.symbol != order.symbol:
            raise ValueError("execution.exchange/symbol no coincide con order.exchange/symbol.")
        if position.exchange != order.exchange or position.symbol != order.symbol:
            raise ValueError("position.exchange/symbol no coincide con order.exchange/symbol.")
        if trade is not None:
            if trade.exchange != order.exchange or trade.symbol != order.symbol:
                raise ValueError("trade.exchange/symbol no coincide con order.exchange/symbol.")
            if trade.exit_execution_id != execution.id:
                raise ValueError("trade.exit_execution_id no coincide con execution.id.")
        if pnl_snapshot is not None:
            if pnl_snapshot.exchange != order.exchange or pnl_snapshot.symbol != order.symbol:
                raise ValueError("pnl_snapshot.exchange/symbol no coincide con order.exchange/symbol.")

    # --- Transacciones atómicas de aceptación/cancelación (Etapa 6.7) ------
    #
    # save_pending_fill_transaction NO se crea como método nuevo: llenar una
    # orden PENDING con reserva usa exactamente save_fill_transaction() de
    # arriba -- la operación SQL (UPSERT Order a FILLED + INSERT Execution +
    # UPSERT Position/CashBalance + INSERT opcional Trade/snapshots) no
    # distingue si la Order venía de NEW (submit_market_order, Etapa 6.4) o
    # de PENDING con reserva (fill_pending_order, Etapa 6.7) -- ver
    # ARQUITECTURA_PAPER_TRADING.md §21.5.

    def save_order_acceptance_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        """Persiste atómicamente una Order recién aceptada (PENDING, con
        reserva) junto con el CashBalance/Position que la reserva afectó.
        El que no cambió se re-guarda tal cual (UPSERT idempotente, sin
        efecto real) -- más simple que persistir condicionalmente según
        BUY/SELL."""
        self._validate_order_balances_consistency(order, cash_balance, position)
        self._save_order_and_balances_transaction(order, cash_balance, position)

    def save_order_cancellation_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        """Persiste atómicamente una Order cancelada (CANCELLED, reserva ya
        liberada) junto con el CashBalance/Position ya actualizados. Misma
        operación exacta que save_order_acceptance_transaction(): ver
        _save_order_and_balances_transaction()."""
        self._validate_order_balances_consistency(order, cash_balance, position)
        self._save_order_and_balances_transaction(order, cash_balance, position)

    def _save_order_and_balances_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        conn = self._get_connection()
        try:
            self._upsert_order(conn, order)
            self._upsert_cash_balance(conn, cash_balance)
            self._upsert_position(conn, position)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validate_order_balances_consistency(order: Order, cash_balance: CashBalance, position: Position) -> None:
        """Mismo criterio que _validate_fill_consistency (Paso 15 de la
        Etapa 6.3): no es lógica de negocio, solo confirma que las
        entidades recibidas realmente pertenecen entre sí antes de escribir
        nada."""
        if position.exchange != order.exchange or position.symbol != order.symbol:
            raise ValueError("position.exchange/symbol no coincide con order.exchange/symbol.")

    # --- PnL realizado: fuente de verdad y reconciliación ------------------

    def calculate_realized_pnl(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None,
    ) -> Decimal:
        conditions = []
        params: list = []
        if exchange is not None:
            conditions.append("exchange = ?")
            params.append(exchange)
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT net_pnl FROM paper_trading_trades {where_sql}", params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        total = Decimal("0")
        for (net_pnl_text,) in rows:
            total += text_to_decimal(net_pnl_text)
        return total

    def check_position_pnl_consistency(self, exchange: str, symbol: str) -> bool:
        position = self.get_position(exchange, symbol)
        if position is None:
            return False
        recalculated = self.calculate_realized_pnl(exchange=exchange, symbol=symbol)
        return position.realized_pnl_to_date == recalculated

    # --- Reconciliación (Etapa 6.8) ----------------------------------------

    def save_reconciliation_audit_record(self, audit_record: ReconciliationAuditRecord) -> None:
        conn = self._get_connection()
        try:
            self._insert_reconciliation_audit(conn, audit_record)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _insert_reconciliation_audit(conn: sqlite3.Connection, audit_record: ReconciliationAuditRecord) -> None:
        """INSERT simple, sin ON CONFLICT: la tabla de auditoría es
        histórica e inmutable (§22.9), como paper_trading_executions/_trades."""
        conn.execute(
            f"""
            INSERT INTO paper_trading_reconciliation_audit ({', '.join(_RECONCILIATION_AUDIT_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_RECONCILIATION_AUDIT_COLUMNS))})
            """,
            (
                audit_record.id, datetime_to_text(audit_record.started_at),
                datetime_to_text(audit_record.completed_at), int(audit_record.dry_run),
                int(audit_record.success), audit_record.issue_count, audit_record.repaired_count,
                audit_record.report_json, audit_record.operations_json, audit_record.error_message,
            ),
        )

    def save_reconciliation_transaction(
        self,
        cash_balances: list[CashBalance],
        positions: list[Position],
        audit_record: ReconciliationAuditRecord,
    ) -> None:
        """Persiste atómicamente los CashBalance/Position ya recalculados por
        una reparación real, junto con su fila de auditoría (§22.8). Nunca
        toca Order/Execution/Trade/snapshots."""
        conn = self._get_connection()
        try:
            for cash_balance in cash_balances:
                self._upsert_cash_balance(conn, cash_balance)
            for position in positions:
                self._upsert_position(conn, position)
            self._insert_reconciliation_audit(conn, audit_record)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- Automatización de inspecciones (Etapa 6.9) ------------------------

    @staticmethod
    def _row_to_inspection_run(row) -> ScheduledInspectionRun:
        return deserialize_inspection_run(dict(zip(_INSPECTION_RUN_COLUMNS, row)))

    @staticmethod
    def _row_to_inspection_alert(row) -> InspectionAlert:
        return deserialize_inspection_alert(dict(zip(_INSPECTION_ALERT_COLUMNS, row)))

    def get_latest_successful_inspection_run(self) -> Optional[ScheduledInspectionRun]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_INSPECTION_RUN_COLUMNS)} FROM paper_trading_inspection_runs "
                "WHERE success = 1 ORDER BY started_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_inspection_run(row) if row else None

    def get_latest_inspection_run(self) -> Optional[ScheduledInspectionRun]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_INSPECTION_RUN_COLUMNS)} FROM paper_trading_inspection_runs "
                "ORDER BY started_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_inspection_run(row) if row else None

    def fetch_inspection_runs(self, limit: Optional[int] = None) -> list[ScheduledInspectionRun]:
        self._validate_limit(limit)
        limit_sql = ""
        params: list = []
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_INSPECTION_RUN_COLUMNS)} FROM paper_trading_inspection_runs "
                f"ORDER BY started_at DESC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_inspection_run(row) for row in rows]

    def fetch_pending_inspection_alerts(self, limit: Optional[int] = None) -> list[InspectionAlert]:
        self._validate_limit(limit)
        limit_sql = ""
        params: list = [AlertStatus.PENDING.value]
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_INSPECTION_ALERT_COLUMNS)} FROM paper_trading_inspection_alerts "
                f"WHERE status = ? ORDER BY created_at ASC {limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_inspection_alert(row) for row in rows]

    def get_inspection_alert_by_deduplication_key(self, deduplication_key: str) -> Optional[InspectionAlert]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_INSPECTION_ALERT_COLUMNS)} FROM paper_trading_inspection_alerts "
                "WHERE deduplication_key = ?",
                (deduplication_key,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_inspection_alert(row) if row else None

    @staticmethod
    def _insert_inspection_run(conn: sqlite3.Connection, run: ScheduledInspectionRun) -> None:
        row = serialize_inspection_run(run)
        conn.execute(
            f"""
            INSERT INTO paper_trading_inspection_runs ({', '.join(_INSPECTION_RUN_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_INSPECTION_RUN_COLUMNS))})
            """,
            tuple(row[column] for column in _INSPECTION_RUN_COLUMNS),
        )

    @staticmethod
    def _insert_inspection_alert(conn: sqlite3.Connection, alert: InspectionAlert) -> None:
        row = serialize_inspection_alert(alert)
        conn.execute(
            f"""
            INSERT INTO paper_trading_inspection_alerts ({', '.join(_INSPECTION_ALERT_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_INSPECTION_ALERT_COLUMNS))})
            """,
            tuple(row[column] for column in _INSPECTION_ALERT_COLUMNS),
        )

    def save_inspection_run_transaction(
        self, run: ScheduledInspectionRun, alerts: list[InspectionAlert],
    ) -> None:
        """Persiste atómicamente (todo o nada) una corrida y todas sus
        alertas nuevas (§23.8). Nunca toca Order/Execution/Trade/
        CashBalance/Position."""
        conn = self._get_connection()
        try:
            self._insert_inspection_run(conn, run)
            for alert in alerts:
                self._insert_inspection_alert(conn, alert)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_inspection_alert_delivery(
        self,
        alert_id: str,
        status: AlertStatus,
        delivery_attempts: int,
        last_error: Optional[str],
        delivered_at,
    ) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE paper_trading_inspection_alerts "
                "SET status = ?, delivery_attempts = ?, last_error = ?, delivered_at = ? WHERE id = ?",
                (status.value, delivery_attempts, last_error, optional_datetime_to_text(delivered_at), alert_id),
            )
            conn.commit()
        finally:
            conn.close()

    # --- Idempotencia de entrega por canal (Etapa 6.10.1, §25.2) -----------

    @staticmethod
    def _row_to_alert_channel_delivery(row) -> InspectionAlertChannelDelivery:
        return InspectionAlertChannelDelivery(
            alert_id=row[0], channel_name=row[1], status=AlertStatus(row[2]), delivery_attempts=row[3],
            last_error=row[4], delivered_at=optional_text_to_datetime(row[5]), updated_at=text_to_datetime(row[6]),
        )

    def get_alert_channel_delivery(
        self, alert_id: str, channel_name: str,
    ) -> Optional[InspectionAlertChannelDelivery]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_ALERT_CHANNEL_DELIVERY_COLUMNS)} "
                "FROM paper_trading_inspection_alert_channel_deliveries WHERE alert_id = ? AND channel_name = ?",
                (alert_id, channel_name),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        return self._row_to_alert_channel_delivery(row) if row else None

    def fetch_alert_channel_deliveries(self, alert_id: str) -> list[InspectionAlertChannelDelivery]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_ALERT_CHANNEL_DELIVERY_COLUMNS)} "
                "FROM paper_trading_inspection_alert_channel_deliveries WHERE alert_id = ? "
                "ORDER BY channel_name ASC",
                (alert_id,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [self._row_to_alert_channel_delivery(row) for row in rows]

    def upsert_alert_channel_delivery(self, delivery: InspectionAlertChannelDelivery) -> None:
        conn = self._get_connection()
        try:
            self._upsert_alert_channel_delivery(conn, delivery)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _upsert_alert_channel_delivery(conn: sqlite3.Connection, delivery: InspectionAlertChannelDelivery) -> None:
        conn.execute(
            f"""
            INSERT INTO paper_trading_inspection_alert_channel_deliveries
                ({', '.join(_ALERT_CHANNEL_DELIVERY_COLUMNS)})
            VALUES ({', '.join(['?'] * len(_ALERT_CHANNEL_DELIVERY_COLUMNS))})
            ON CONFLICT(alert_id, channel_name) DO UPDATE SET
                status=excluded.status, delivery_attempts=excluded.delivery_attempts,
                last_error=excluded.last_error, delivered_at=excluded.delivered_at, updated_at=excluded.updated_at
            """,
            (
                delivery.alert_id, delivery.channel_name, delivery.status.value, delivery.delivery_attempts,
                delivery.last_error, optional_datetime_to_text(delivery.delivered_at),
                datetime_to_text(delivery.updated_at),
            ),
        )
