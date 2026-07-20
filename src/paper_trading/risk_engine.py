"""
RiskEngine -- validación previa a aceptar una orden (Etapa 6.2).

Motor puro (ver docs/ARQUITECTURA_PAPER_TRADING.md §8): solo lee los
valores recibidos y devuelve un veredicto (RiskValidationResult). No
cambia Order.status, no reserva CashBalance.reserved_balance ni
Position.reserved_quantity, no persiste nada -- la reserva real de
capital/cantidad es responsabilidad de un futuro servicio (Etapa 6.4),
no de este motor.

Alcance de este MVP: solo BUY/SELL MARKET sobre posiciones LONG/FLAT.
SHORT queda diferido (§5.1). La comisión estimada de una SELL no se
valida contra CashBalance en este MVP: la comisión de venta se
descuenta del producto de la venta al ejecutarse (ver
position_engine.py), no se reserva por adelantado -- consistente con
que este motor "no reserva saldo".

Precedencia de reglas (determinista, documentada explícitamente aquí
porque el enunciado de la Etapa 6.2 la exige): tipo de orden -> estado
de la orden -> side de la posición -> cantidad disponible (solo SELL)
-> capital disponible (solo BUY) -> máximo por orden (solo BUY) ->
máximo por posición (solo BUY). Se evalúa en ese orden exacto y se
devuelve el primer rechazo encontrado; ninguna excepción se lanza por
un rechazo de riesgo normal (las excepciones quedan reservadas para
argumentos estructuralmente imposibles, ej. un market_price <= 0).
"""

from datetime import datetime
from decimal import Decimal

from src.paper_trading.enums import OrderSide, OrderStatus, OrderType, PositionSide
from src.paper_trading.models import CashBalance, Order, Position, RiskValidationResult

ZERO = Decimal("0")


class RiskEngine:
    """Validación pura de riesgo previa a aceptar una orden propuesta."""

    @staticmethod
    def validate_order(
        order: Order,
        cash_balance: CashBalance,
        position: Position,
        market_price: Decimal,
        max_order_value: Decimal,
        max_position_value: Decimal,
        fee_rate: Decimal,
        timestamp: datetime,
        rules_version: str,
    ) -> RiskValidationResult:
        if market_price <= ZERO:
            raise ValueError("market_price debe ser mayor que 0.")
        if fee_rate < ZERO:
            raise ValueError("fee_rate no puede ser negativo.")

        limits_used = {
            "max_order_value": max_order_value,
            "max_position_value": max_position_value,
            "fee_rate": fee_rate,
        }

        def _rejected(code: str, message: str, metrics_used: dict) -> RiskValidationResult:
            return RiskValidationResult(
                approved=False, code=code, message=message, metrics_used=metrics_used,
                limits_used=limits_used, timestamp=timestamp, rules_version=rules_version,
            )

        # 1. tipo de orden
        if order.order_type != OrderType.MARKET:
            return _rejected(
                "ORDER_TYPE_UNSUPPORTED", f"Tipo de orden no soportado: {order.order_type.value}.", {},
            )

        # 2. estado de la orden
        if order.status != OrderStatus.NEW:
            return _rejected(
                "ORDER_STATUS_INVALID",
                f"Solo se validan órdenes en estado NEW; estado recibido: {order.status.value}.", {},
            )

        # 3. side de la posición
        if position.side == PositionSide.SHORT:
            return _rejected(
                "POSITION_SIDE_UNSUPPORTED", "Posiciones SHORT no están soportadas en esta iteración.", {},
            )

        if order.side == OrderSide.SELL:
            metrics_used = {
                "order_quantity": order.quantity,
                "available_quantity": position.available_quantity,
            }
            # 4. cantidad disponible (solo SELL)
            if position.side == PositionSide.FLAT:
                return _rejected(
                    "SELL_WITHOUT_POSITION", "No se puede vender: la posición está FLAT.", metrics_used,
                )
            if order.quantity > position.available_quantity:
                return _rejected(
                    "INSUFFICIENT_AVAILABLE_QUANTITY",
                    f"order.quantity ({order.quantity}) supera available_quantity "
                    f"({position.available_quantity}).",
                    metrics_used,
                )
            return RiskValidationResult(
                approved=True, code="APPROVED", message="Orden SELL dentro de la cantidad disponible.",
                metrics_used=metrics_used, limits_used=limits_used, timestamp=timestamp,
                rules_version=rules_version,
            )

        # order.side == OrderSide.BUY
        estimated_order_value = order.quantity * market_price
        estimated_fee = estimated_order_value * fee_rate
        required_cash = estimated_order_value + estimated_fee
        current_position_value = (
            position.quantity * market_price if position.side == PositionSide.LONG else ZERO
        )
        metrics_used = {
            "estimated_order_value": estimated_order_value,
            "estimated_fee": estimated_fee,
            "required_cash": required_cash,
            "available_balance": cash_balance.available_balance,
            "current_position_value": current_position_value,
        }

        # 5. capital disponible (solo BUY)
        if required_cash > cash_balance.available_balance:
            return _rejected(
                "INSUFFICIENT_AVAILABLE_CASH",
                f"required_cash ({required_cash}) supera available_balance "
                f"({cash_balance.available_balance}).",
                metrics_used,
            )

        # 6. máximo por orden (solo BUY)
        if estimated_order_value > max_order_value:
            return _rejected(
                "MAX_ORDER_VALUE_EXCEEDED",
                f"estimated_order_value ({estimated_order_value}) supera max_order_value "
                f"({max_order_value}).",
                metrics_used,
            )

        # 7. máximo por posición (solo BUY)
        resulting_position_value = current_position_value + estimated_order_value
        if resulting_position_value > max_position_value:
            return _rejected(
                "MAX_POSITION_VALUE_EXCEEDED",
                f"La posición resultante ({resulting_position_value}) supera max_position_value "
                f"({max_position_value}).",
                metrics_used,
            )

        return RiskValidationResult(
            approved=True, code="APPROVED", message="Orden BUY dentro de los límites de riesgo.",
            metrics_used=metrics_used, limits_used=limits_used, timestamp=timestamp,
            rules_version=rules_version,
        )
