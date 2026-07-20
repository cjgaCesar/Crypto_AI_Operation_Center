"""
FillEngine -- simulación de llenado de órdenes MARKET (Etapa 6.2).

Motor puro: recibe modelos Pydantic y valores explícitos (incluyendo
timestamp e id, nunca generados internamente), devuelve nuevos modelos,
nunca muta los que recibe, sin efectos secundarios. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §9 (motor de llenado sin
bid/ask/profundidad, consumiendo directamente un precio de referencia
en vez de un OrderBook).

Alcance de este MVP (ver ARQUITECTURA_PAPER_TRADING.md §20):
- Solo OrderType.MARKET (LIMIT diferido, ver enums.py).
- Llena siempre el 100% del remanente en una única Execution -- este
  motor no genera fills parciales por sí mismo (un fill parcial en la
  vida real de una Order solo existiría si esta función se invoca más
  de una vez sobre la misma Order con remanentes distintos cada vez,
  algo que este motor no orquesta ni decide).
- Sin slippage, sin latencia, sin liquidez: el precio de ejecución es
  siempre exactamente market_price.

Convención de excepciones de este módulo (no se modifica exceptions.py,
ver enunciado de la Etapa 6.2 -- el dominio de 6.1 se considera
estable): InvalidOrderTransitionError para un order_type o status que
este motor no puede procesar; OverFillError cuando no queda cantidad
remanente que llenar (una orden sin remanente que de todas formas se
intenta llenar es, en el sentido de la arquitectura, un intento de
llenado imposible -- ver ARQUITECTURA_PAPER_TRADING.md §4, "over-fill").
"""

from datetime import datetime
from decimal import Decimal

from src.paper_trading.enums import OrderStatus, OrderType
from src.paper_trading.exceptions import InvalidOrderTransitionError, OverFillError
from src.paper_trading.models import Execution, Order
from src.paper_trading.results import FillResult

ZERO = Decimal("0")

_FILLABLE_STATUSES = (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED)


class FillEngine:
    """Simula el llenado de órdenes MARKET contra un precio de referencia explícito."""

    @staticmethod
    def execute_market_order(
        order: Order,
        market_price: Decimal,
        fee_rate: Decimal,
        executed_at: datetime,
        execution_id: str,
    ) -> FillResult:
        """Llena el 100% del remanente de `order` a `market_price`.

        No muta `order`: devuelve una Order nueva (FillResult.order) y
        una Execution nueva (FillResult.execution).
        """
        if order.order_type != OrderType.MARKET:
            raise InvalidOrderTransitionError(
                f"FillEngine solo procesa OrderType.MARKET; se recibió {order.order_type.value}."
            )
        if order.status not in _FILLABLE_STATUSES:
            raise InvalidOrderTransitionError(
                f"No se puede llenar una orden en estado {order.status.value}; "
                "se esperaba PENDING o PARTIALLY_FILLED."
            )
        if market_price <= ZERO:
            raise ValueError("market_price debe ser mayor que 0.")
        if fee_rate < ZERO:
            raise ValueError("fee_rate no puede ser negativo.")

        remaining_quantity = order.quantity - order.filled_quantity
        if remaining_quantity <= ZERO:
            raise OverFillError(
                "La orden no tiene cantidad remanente para llenar "
                f"(quantity={order.quantity}, filled_quantity={order.filled_quantity})."
            )

        fee = market_price * remaining_quantity * fee_rate
        execution = Execution(
            id=execution_id,
            order_id=order.id,
            exchange=order.exchange,
            symbol=order.symbol,
            quantity=remaining_quantity,
            price=market_price,
            fee=fee,
            executed_at=executed_at,
        )

        total_filled = order.filled_quantity + remaining_quantity
        if order.filled_quantity == ZERO:
            new_average_fill_price = market_price
        else:
            new_average_fill_price = (
                (order.average_fill_price * order.filled_quantity) + (market_price * remaining_quantity)
            ) / total_filled

        updated_fields = order.model_dump()
        updated_fields.update(
            status=OrderStatus.FILLED,
            filled_quantity=total_filled,
            average_fill_price=new_average_fill_price,
            updated_at=executed_at,
        )
        updated_order = Order(**updated_fields)

        return FillResult(order=updated_order, execution=execution)
