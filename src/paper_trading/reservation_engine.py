"""
ReservationEngine -- reserva y liberación de recursos al aceptar/llenar/
cancelar una orden (Etapa 6.7).

Motor puro, mismo perfil que fill_engine.py/position_engine.py/
risk_engine.py/pnl_engine.py: recibe modelos Pydantic y valores
explícitos (incluyendo timestamp, nunca generado internamente), nunca
muta los que recibe, sin efectos secundarios. No conoce
PaperTradingRepository, PaperTradingService ni PaperTradingApplication,
no usa sqlite3/logging/datetime.now()/uuid.uuid4()/configuración global.

Ver docs/ARQUITECTURA_PAPER_TRADING.md §21.4 para el diseño completo.
Resumen:

- `reserve_for_order()` asume que RiskEngine.validate_order() ya aprobó
  la orden (es responsabilidad del Service llamarlo antes) -- por eso
  un fallo de saldo/cantidad aquí (`InsufficientReservedCashError`/
  `InsufficientReservedQuantityError`) representa un estado imposible o
  una carrera, no un rechazo de riesgo normal.
- `release_for_order()` lee los datos de la reserva desde la propia
  `order` (`reserved_notional`/`reserved_fee`/`reserved_quantity`, ver
  §21.2), nunca los recibe como parámetro aparte: evita que quien llama
  pase por error un valor reservado distinto del que realmente se
  guardó. Sirve tanto para llenar como para cancelar (liberar es
  idéntico en ambos casos; lo que sigue después difiere).
"""

from datetime import datetime
from decimal import Decimal

from src.paper_trading.enums import OrderSide, OrderStatus, OrderType, PositionSide
from src.paper_trading.exceptions import (
    InsufficientReservedCashError,
    InsufficientReservedQuantityError,
    InvalidOrderStateError,
    PaperTradingDomainError,
    ReservationAlreadyReleasedError,
    ReservationNotFoundError,
)
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.reservation_results import ReservationReleaseResult, ReservationResult

ZERO = Decimal("0")


class ReservationEngine:
    """Reserva/libera capital o cantidad para una orden, sin liquidar nada."""

    @staticmethod
    def reserve_for_order(
        order: Order,
        cash_balance: CashBalance,
        position: Position,
        market_price: Decimal,
        fee_rate: Decimal,
        timestamp: datetime,
    ) -> ReservationResult:
        if order.order_type != OrderType.MARKET:
            raise InvalidOrderStateError(
                f"ReservationEngine solo procesa OrderType.MARKET; se recibió {order.order_type.value}."
            )
        if order.status != OrderStatus.NEW:
            raise InvalidOrderStateError(
                f"Solo se puede reservar sobre una orden NEW; estado actual: {order.status.value}."
            )
        if market_price <= ZERO:
            raise ValueError("market_price debe ser mayor que 0.")
        if fee_rate < ZERO:
            raise ValueError("fee_rate no puede ser negativo.")
        if position.side == PositionSide.SHORT:
            raise PaperTradingDomainError(
                "ReservationEngine no soporta posiciones SHORT en esta iteración (ver §5.1)."
            )

        if order.side == OrderSide.BUY:
            return ReservationEngine._reserve_buy(order, cash_balance, position, market_price, fee_rate, timestamp)
        return ReservationEngine._reserve_sell(order, cash_balance, position, market_price, timestamp)

    @staticmethod
    def _reserve_buy(
        order: Order, cash_balance: CashBalance, position: Position,
        market_price: Decimal, fee_rate: Decimal, timestamp: datetime,
    ) -> ReservationResult:
        reserved_notional = order.quantity * market_price
        reserved_fee = reserved_notional * fee_rate
        required = reserved_notional + reserved_fee

        if required > cash_balance.available_balance:
            raise InsufficientReservedCashError(
                f"required ({required}) supera available_balance ({cash_balance.available_balance})."
            )

        new_cash_balance = CashBalance(**{
            **cash_balance.model_dump(),
            "reserved_balance": cash_balance.reserved_balance + required,
            "updated_at": timestamp,
        })
        updated_order = Order(**{
            **order.model_dump(),
            "status": OrderStatus.PENDING,
            "reserved_price": market_price,
            "reserved_notional": reserved_notional,
            "reserved_fee": reserved_fee,
            "updated_at": timestamp,
        })
        return ReservationResult(order=updated_order, cash_balance=new_cash_balance, position=position)

    @staticmethod
    def _reserve_sell(
        order: Order, cash_balance: CashBalance, position: Position, market_price: Decimal, timestamp: datetime,
    ) -> ReservationResult:
        if position.side != PositionSide.LONG:
            raise InsufficientReservedQuantityError(
                f"No hay posición LONG sobre la que reservar en {order.exchange}:{order.symbol}."
            )
        if order.quantity > position.available_quantity:
            raise InsufficientReservedQuantityError(
                f"order.quantity ({order.quantity}) supera available_quantity "
                f"({position.available_quantity})."
            )

        new_position = Position(**{
            **position.model_dump(),
            "reserved_quantity": position.reserved_quantity + order.quantity,
            "updated_at": timestamp,
        })
        updated_order = Order(**{
            **order.model_dump(),
            "status": OrderStatus.PENDING,
            "reserved_price": market_price,
            "reserved_quantity": order.quantity,
            "updated_at": timestamp,
        })
        return ReservationResult(order=updated_order, cash_balance=cash_balance, position=new_position)

    @staticmethod
    def release_for_order(
        order: Order,
        cash_balance: CashBalance,
        position: Position,
        timestamp: datetime,
    ) -> ReservationReleaseResult:
        if order.status != OrderStatus.PENDING:
            raise InvalidOrderStateError(
                f"Solo se puede liberar la reserva de una orden PENDING; estado actual: {order.status.value}."
            )

        if order.side == OrderSide.BUY:
            return ReservationEngine._release_buy(order, cash_balance, position, timestamp)
        return ReservationEngine._release_sell(order, cash_balance, position, timestamp)

    @staticmethod
    def _release_buy(
        order: Order, cash_balance: CashBalance, position: Position, timestamp: datetime,
    ) -> ReservationReleaseResult:
        if order.reserved_notional is None or order.reserved_fee is None:
            raise ReservationNotFoundError(
                f"La orden {order.id} no tiene datos de reserva (reserved_notional/reserved_fee)."
            )
        released = order.reserved_notional + order.reserved_fee
        if released > cash_balance.reserved_balance:
            raise ReservationAlreadyReleasedError(
                f"Liberar {released} dejaría reserved_balance negativo "
                f"(actual: {cash_balance.reserved_balance})."
            )

        new_cash_balance = CashBalance(**{
            **cash_balance.model_dump(),
            "reserved_balance": cash_balance.reserved_balance - released,
            "updated_at": timestamp,
        })
        return ReservationReleaseResult(cash_balance=new_cash_balance, position=position)

    @staticmethod
    def _release_sell(
        order: Order, cash_balance: CashBalance, position: Position, timestamp: datetime,
    ) -> ReservationReleaseResult:
        if order.reserved_quantity is None:
            raise ReservationNotFoundError(f"La orden {order.id} no tiene datos de reserva (reserved_quantity).")
        if order.reserved_quantity > position.reserved_quantity:
            raise ReservationAlreadyReleasedError(
                f"Liberar {order.reserved_quantity} dejaría reserved_quantity negativo "
                f"(actual: {position.reserved_quantity})."
            )

        new_position = Position(**{
            **position.model_dump(),
            "reserved_quantity": position.reserved_quantity - order.reserved_quantity,
            "updated_at": timestamp,
        })
        return ReservationReleaseResult(cash_balance=cash_balance, position=new_position)
