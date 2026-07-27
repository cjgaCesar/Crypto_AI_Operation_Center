"""
CLI administrativa para operar manualmente órdenes de Paper Trading
(Etapa 6.19).

Uso:
    python -m src.paper_trading.order_cli accept \\
        --exchange Binance --symbol BTCUSDT --side BUY --quantity 0.01 --confirm
    python -m src.paper_trading.order_cli fill --order-id <ORDER_ID> --confirm
    python -m src.paper_trading.order_cli cancel \\
        --order-id <ORDER_ID> --reason "Cancelación manual" --confirm
    python -m src.paper_trading.order_cli submit \\
        --exchange Binance --symbol BTCUSDT --side BUY --quantity 0.01 --format json --confirm

Decisión arquitectónica (Etapa 6.19): esta CLI **no** implementa ningún
caso de uso nuevo -- expone, tal cual, los cuatro casos de uso que
`PaperTradingApplication` ya tiene desde las Etapas 6.5/6.7:

    accept  -> PaperTradingApplication.accept_manual_market_order()
    fill    -> PaperTradingApplication.fill_manual_pending_order()
    cancel  -> PaperTradingApplication.cancel_manual_pending_order()
    submit  -> PaperTradingApplication.submit_manual_market_order()

No calcula riesgo, reservas, comisiones, PnL ni fills: todo eso sigue
viviendo exclusivamente en RiskEngine/ReservationEngine/FillEngine/
PositionEngine/PnLEngine, orquestados por PaperTradingService (Etapas
6.2/6.4/6.7) detrás de PaperTradingApplication. Esta CLI tampoco abre
ninguna conexión sqlite3 ni ejecuta SQL propio: toda persistencia pasa
por el Composition Root (`build_paper_trading_context()`,
`src/paper_trading/composition.py`), reutilizado sin modificar, igual
que ya hacen `reconciliation_cli.py`/`inspection_cli.py`.

Configuración: opera exclusivamente sobre `config/config.yaml` + `.env`
(vía `load_settings()`), la misma base que usa el resto del proyecto --
no admite `--database-path` ni ningún otro override de configuración
(a diferencia de `portfolio_cli.py`, que es de solo lectura): esta CLI
escribe, así que solo debe operar sobre la base oficialmente
configurada. Las pruebas inyectan un contexto de prueba monkeypencheando
el helper privado `_build_context()`, igual que
`reconciliation_cli.py`/`inspection_cli.py`.

Precio de mercado: `accept`/`submit` (y `fill`, si existen otras
posiciones abiertas en otros símbolos) consultan el mismo
`RepositoryMarketPriceProvider` que usa `src/main.py`
(`build_paper_trading()`), sobre una instancia propia de
`SQLiteMarketDataRepository` -- nunca un precio manual ni un
`--price`/`--fill-price` inventado por esta CLI. `fill` respeta la
política ya aprobada "MARKET se llena al precio reservado durante la
aceptación" (§21.3): nunca recalcula el precio de la orden que llena.

Confirmación obligatoria: los cuatro subcomandos escriben o pueden
escribir estado de negocio (simulado). Sin `--confirm`, esta CLI no
construye ningún contexto, no llama a `load_settings()`, no consulta
ningún precio, no genera ningún id y no ejecuta ninguna operación --
devuelve el código de confirmación requerida antes de cualquier otro
efecto. Nunca usa `input()`: es automatizable, no interactiva.

Alcance: solo MARKET, solo posiciones LONG (una SELL reduce/cierra una
posición LONG existente; nunca abre ni aumenta un SHORT). Sin
PostgreSQL, sin backup/restauración -- fuera de esta etapa.
"""

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Sequence

from pydantic import BaseModel

from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.paper_trading.application import PaperTradingApplication, PaperTradingDisabledError
from src.paper_trading.composition import PaperTradingContext, build_paper_trading_context
from src.paper_trading.enums import OrderSide
from src.paper_trading.exceptions import InvalidOrderStateError, PaperTradingDomainError
from src.paper_trading.price_provider import RepositoryMarketPriceProvider
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator
from src.utils.config import load_settings

EXIT_OK = 0
EXIT_ARGUMENT_ERROR = 2
EXIT_CONFIG_ERROR = 3
EXIT_DISABLED = 4
EXIT_CONFIRMATION_REQUIRED = 5
EXIT_RISK_REJECTED = 6
EXIT_INVALID_STATE = 7
EXIT_OPERATIONAL_ERROR = 8
EXIT_UNEXPECTED_ERROR = 9

_CONFIRMATION_MESSAGE = (
    "Confirmation required: pass --confirm to authorize this simulated Paper Trading write."
)
_DISABLED_MESSAGE = "Paper Trading is disabled in configuration."
_UNEXPECTED_MESSAGE = "Order operation failed unexpectedly."

_TABLE_MAX_TEXT_LENGTH = 200
_TABLE_TRUNCATION_MARK = "..."
# Únicos campos de texto libre que este módulo produce (mensaje de riesgo,
# motivo de cancelación); nunca se trunca un id (§19 del ticket).
_TRUNCATABLE_KEYS = {"risk_message", "cancellation_reason"}


class ConfigurationError(Exception):
    """No se pudo cargar la configuración necesaria para operar Paper
    Trading (código de salida 3). Mismo criterio que
    `portfolio_cli.ConfigurationError`: nunca incluye rutas completas
    ni credenciales en su mensaje."""


# --------------------------------------------------------------------------
# Construcción del contexto (Composition Root existente, sin modificar)
# --------------------------------------------------------------------------

def _build_context() -> PaperTradingContext:
    """Construye el `PaperTradingContext` real, igual patrón que
    `reconciliation_cli.py`/`inspection_cli.py`: `load_settings()` +
    `build_paper_trading_context()`, con `SystemClock`/`UUIDIdGenerator`
    reales. A diferencia de esas dos CLIs (que nunca consultan un
    precio), `accept`/`fill`/`submit` sí pueden necesitar uno real -- se
    usa el mismo `RepositoryMarketPriceProvider` que ya usa
    `src/main.py` (`build_paper_trading()`), sobre una instancia propia
    de `SQLiteMarketDataRepository` (cada repositorio SQLite del
    proyecto abre su propia conexión por operación; instanciar otro
    apuntando al mismo archivo es seguro, mismo criterio ya documentado
    en `src/main.py`).
    """
    try:
        settings = load_settings()
    except Exception:
        raise ConfigurationError(
            "Could not load configuration to build the Paper Trading context."
        ) from None

    market_repository = SQLiteMarketDataRepository(settings.database.sqlite_path)
    market_repository.init()

    return build_paper_trading_context(
        config=settings.paper_trading,
        clock=SystemClock(),
        id_generator=UUIDIdGenerator(),
        market_price_provider=RepositoryMarketPriceProvider(market_repository),
    )


# --------------------------------------------------------------------------
# Validación de argumentos
# --------------------------------------------------------------------------

def _side_type(value: str) -> OrderSide:
    try:
        return OrderSide(value)
    except ValueError:
        valid = ", ".join(member.value for member in OrderSide)
        raise argparse.ArgumentTypeError(f"--side must be one of: {valid}") from None


def _quantity_type(value: str) -> Decimal:
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"--quantity must be a valid decimal number, got {value!r}.") from None
    if not quantity.is_finite():
        raise argparse.ArgumentTypeError("--quantity must be a finite number (not NaN/Infinity).")
    if quantity <= Decimal("0"):
        raise argparse.ArgumentTypeError("--quantity must be greater than 0.")
    return quantity


def _non_empty_text_type(flag_name: str) -> Any:
    def _validate(value: str) -> str:
        if not value:
            raise argparse.ArgumentTypeError(f"{flag_name} must not be empty.")
        return value
    return _validate


# --------------------------------------------------------------------------
# Punto de entrada / parser
# --------------------------------------------------------------------------

def _build_common_parser() -> argparse.ArgumentParser:
    """Argumentos globales (`--format`/`--confirm`), compartidos entre el
    parser raíz y cada uno de los cuatro subparsers -- mismo patrón de
    parser padre + `argument_default=argparse.SUPPRESS` aprobado en la
    Etapa 6.18.1 (ver `portfolio_cli._build_common_parser()`): ambos se
    aceptan tanto antes como después del subcomando, sin que el default
    de un subparser sobrescriba silenciosamente un valor ya reconocido
    por el parser raíz."""
    parser = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    parser.add_argument(
        "--format", dest="format", choices=["table", "json"],
        help="Formato de salida (default: table).",
    )
    parser.add_argument(
        "--confirm", dest="confirm", action="store_true",
        help=(
            "Obligatorio: autoriza esta escritura real (simulada) de Paper Trading. "
            "Sin este flag, no se construye ningún contexto, no se consulta ningún "
            "precio ni se ejecuta ninguna operación."
        ),
    )
    return parser


def _add_new_order_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--exchange", required=True, help="Exchange simulado, ej. Binance.")
    parser.add_argument("--symbol", required=True, help="Símbolo, ej. BTCUSDT.")
    parser.add_argument("--side", type=_side_type, required=True, help="BUY o SELL.")
    parser.add_argument("--quantity", type=_quantity_type, required=True, help="Cantidad, Decimal > 0.")


def build_parser() -> argparse.ArgumentParser:
    common = _build_common_parser()

    parser = argparse.ArgumentParser(
        prog="python -m src.paper_trading.order_cli",
        description=(
            "CLI administrativa para operar manualmente órdenes MARKET simuladas de "
            "Paper Trading (Etapa 6.19). Toda escritura requiere --confirm."
        ),
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    accept_parser = subparsers.add_parser(
        "accept", parents=[common],
        help="Acepta una orden MARKET manual: valida riesgo y, si se aprueba, reserva recursos (NEW -> PENDING).",
    )
    _add_new_order_arguments(accept_parser)

    fill_parser = subparsers.add_parser(
        "fill", parents=[common], help="Llena una orden PENDING previamente aceptada (PENDING -> FILLED).",
    )
    fill_parser.add_argument("--order-id", dest="order_id", required=True, help="Id de la orden PENDING a llenar.")

    cancel_parser = subparsers.add_parser(
        "cancel", parents=[common], help="Cancela una orden PENDING, liberando su reserva (PENDING -> CANCELLED).",
    )
    cancel_parser.add_argument("--order-id", dest="order_id", required=True, help="Id de la orden PENDING a cancelar.")
    cancel_parser.add_argument(
        "--reason", dest="reason", required=True, type=_non_empty_text_type("--reason"),
        help="Motivo de la cancelación (obligatorio, no vacío).",
    )

    submit_parser = subparsers.add_parser(
        "submit", parents=[common],
        help="Somete una orden MARKET de punta a punta (aceptar + reservar + llenar + persistir).",
    )
    _add_new_order_arguments(submit_parser)

    return parser


# --------------------------------------------------------------------------
# Ejecución de comandos (delega siempre en PaperTradingApplication)
# --------------------------------------------------------------------------

def _run_command(context: PaperTradingContext, args: argparse.Namespace) -> dict:
    app: PaperTradingApplication = context.application

    if args.command == "accept":
        result = app.accept_manual_market_order(
            exchange=args.exchange, symbol=args.symbol, side=args.side, quantity=args.quantity,
        )
        return _accept_payload(result)

    if args.command == "fill":
        result = app.fill_manual_pending_order(args.order_id)
        return _fill_payload(result)

    if args.command == "cancel":
        result = app.cancel_manual_pending_order(args.order_id, args.reason)
        return _cancel_payload(result)

    result = app.submit_manual_market_order(
        exchange=args.exchange, symbol=args.symbol, side=args.side, quantity=args.quantity,
    )
    return _submit_payload(result)


def _exit_code_for(command: str, payload: dict) -> int:
    if command in ("accept", "submit") and not payload["approved"]:
        return EXIT_RISK_REJECTED
    return EXIT_OK


# --------------------------------------------------------------------------
# Construcción de la salida (solo campos reales del resultado devuelto)
# --------------------------------------------------------------------------

def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _accept_payload(result) -> dict:
    payload = {
        "approved": result.success,
        "order_id": result.order.id,
        "status": result.order.status,
        "exchange": result.order.exchange,
        "symbol": result.order.symbol,
        "side": result.order.side,
        "quantity": result.order.quantity,
        "risk_code": result.risk_result.code,
        "risk_message": result.risk_result.message,
    }
    if result.success:
        payload.update({
            "reserved_price": result.order.reserved_price,
            "reserved_notional": result.order.reserved_notional,
            "reserved_fee": result.order.reserved_fee,
            "reserved_quantity": result.order.reserved_quantity,
            "reservation_created": result.reservation_created,
            "cash_balance_total": result.cash_balance.total_balance,
            "cash_balance_reserved": result.cash_balance.reserved_balance,
            "position_side": result.position.side,
            "position_quantity": result.position.quantity,
            "position_reserved_quantity": result.position.reserved_quantity,
        })
    return {key: _serialize(value) for key, value in payload.items()}


def _fill_payload(result) -> dict:
    payload = {
        "order_id": result.order.id,
        "status": result.order.status,
        "execution_id": result.execution.id,
        "quantity_executed": result.execution.quantity,
        "execution_price": result.execution.price,
        "fee": result.execution.fee,
        "position_side": result.position.side,
        "position_quantity": result.position.quantity,
        "cash_balance_total": result.cash_balance.total_balance,
        "cash_balance_reserved": result.cash_balance.reserved_balance,
        "trade_id": result.trade.id if result.trade is not None else None,
        "reservation_released": result.reservation_released,
    }
    return {key: _serialize(value) for key, value in payload.items()}


def _cancel_payload(result) -> dict:
    payload = {
        "order_id": result.order.id,
        "status": result.order.status,
        "cancellation_reason": result.order.cancellation_reason,
        "reservation_released": result.reservation_released,
        "cash_balance_total": result.cash_balance.total_balance,
        "cash_balance_reserved": result.cash_balance.reserved_balance,
        "position_side": result.position.side,
        "position_quantity": result.position.quantity,
        "position_reserved_quantity": result.position.reserved_quantity,
    }
    return {key: _serialize(value) for key, value in payload.items()}


def _submit_payload(result) -> dict:
    payload = {
        "approved": result.success,
        "order_id": result.order.id,
        "status": result.order.status,
        "exchange": result.order.exchange,
        "symbol": result.order.symbol,
        "side": result.order.side,
        "quantity": result.order.quantity,
        "risk_code": result.risk_result.code,
        "risk_message": result.risk_result.message,
    }
    if result.success:
        payload.update({
            "execution_id": result.execution.id,
            "execution_price": result.execution.price,
            "fee": result.execution.fee,
            "position_side": result.position.side,
            "position_quantity": result.position.quantity,
            "cash_balance_total": result.cash_balance.total_balance,
            "cash_balance_reserved": result.cash_balance.reserved_balance,
            "trade_id": result.trade.id if result.trade is not None else None,
            "realized_pnl_cumulative": (
                result.pnl_snapshot.realized_pnl_cumulative if result.pnl_snapshot is not None else None
            ),
            "unrealized_pnl": result.pnl_snapshot.unrealized_pnl if result.pnl_snapshot is not None else None,
        })
    return {key: _serialize(value) for key, value in payload.items()}


# --------------------------------------------------------------------------
# Formato de salida (solo biblioteca estándar: sin tabulate/rich/pandas)
# --------------------------------------------------------------------------

def _format_value_for_table(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if key in _TRUNCATABLE_KEYS and len(text) > _TABLE_MAX_TEXT_LENGTH:
        return text[: _TABLE_MAX_TEXT_LENGTH - len(_TABLE_TRUNCATION_MARK)] + _TABLE_TRUNCATION_MARK
    return text


def render_key_value(payload: dict) -> str:
    return "\n".join(f"{key}: {_format_value_for_table(key, value)}" for key, value in payload.items())


def _json_default(value: Any):
    if isinstance(value, (BaseModel,)):
        raise TypeError("dataclass/model payloads must be pre-serialized before rendering as JSON")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def render_json(payload: dict) -> str:
    return json.dumps(payload, default=_json_default, indent=2)


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_format = getattr(args, "format", "table")
    confirmed = getattr(args, "confirm", False)

    # §15/§31: la confirmación se valida antes de construir cualquier
    # dependencia -- ni load_settings(), ni el contexto, ni el precio,
    # ni ningún id se generan si falta --confirm.
    if not confirmed:
        print(_CONFIRMATION_MESSAGE, file=sys.stderr)
        return EXIT_CONFIRMATION_REQUIRED

    context: Optional[PaperTradingContext] = None
    try:
        context = _build_context()
        payload = _run_command(context, args)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except PaperTradingDisabledError:
        print(_DISABLED_MESSAGE, file=sys.stderr)
        return EXIT_DISABLED
    except InvalidOrderStateError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID_STATE
    except ValueError as exc:
        # `PaperTradingApplication.fill_manual_pending_order()` es el único
        # caso de uso que levanta un ValueError (no InvalidOrderStateError)
        # cuando la orden no existe -- no hay un OrderNotFoundError real en
        # exceptions.py que capturar (ver §22 del ticket: "no asumir nombres
        # inexistentes"). Se reclasifica aquí a la misma categoría que un
        # estado inválido (7) releyendo el pedido ya inyectado por el
        # Composition Root (nunca SQL propio); cualquier otro ValueError
        # (ej. precio de mercado faltante) sigue siendo un error operativo
        # controlado (8).
        order_id = getattr(args, "order_id", None)
        if context is not None and order_id is not None and context.repository.get_order(order_id) is None:
            print(str(exc), file=sys.stderr)
            return EXIT_INVALID_STATE
        print(str(exc), file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    except PaperTradingDomainError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    except Exception:
        print(_UNEXPECTED_MESSAGE, file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR

    if output_format == "json":
        print(render_json(payload))
    else:
        print(render_key_value(payload))

    return _exit_code_for(args.command, payload)


if __name__ == "__main__":
    raise SystemExit(main())
