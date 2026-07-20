"""
Pruebas para FillEngine (Etapa 6.2): simulación de llenado MARKET.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
from src.paper_trading.exceptions import InvalidOrderTransitionError, OverFillError
from src.paper_trading.fill_engine import FillEngine
from src.paper_trading.models import Order


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(**overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT",
        side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.PENDING,
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


class TestExecuteMarketOrderValidCases:
    def test_fills_a_pending_market_order_completely(self):
        order = _order(quantity=Decimal("0.1"))
        executed_at = _now()
        result = FillEngine.execute_market_order(
            order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            executed_at=executed_at, execution_id="exec-1",
        )
        assert result.order.status == OrderStatus.FILLED
        assert result.order.filled_quantity == Decimal("0.1")
        assert result.order.average_fill_price == Decimal("50000")
        assert result.order.updated_at == executed_at
        assert result.execution.quantity == Decimal("0.1")
        assert result.execution.price == Decimal("50000")

    def test_fee_is_price_times_quantity_times_fee_rate(self):
        order = _order(quantity=Decimal("2"))
        result = FillEngine.execute_market_order(
            order, market_price=Decimal("100"), fee_rate=Decimal("0.01"),
            executed_at=_now(), execution_id="exec-1",
        )
        assert result.execution.fee == Decimal("100") * Decimal("2") * Decimal("0.01")

    def test_zero_fee_rate_is_allowed(self):
        order = _order()
        result = FillEngine.execute_market_order(
            order, market_price=Decimal("50000"), fee_rate=Decimal("0"),
            executed_at=_now(), execution_id="exec-1",
        )
        assert result.execution.fee == Decimal("0")

    def test_completes_remaining_quantity_of_partially_filled_order(self):
        order = _order(
            quantity=Decimal("1"), status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("0.4"), average_fill_price=Decimal("100"),
        )
        result = FillEngine.execute_market_order(
            order, market_price=Decimal("110"), fee_rate=Decimal("0"),
            executed_at=_now(), execution_id="exec-2",
        )
        assert result.execution.quantity == Decimal("0.6")
        assert result.order.filled_quantity == Decimal("1")
        assert result.order.status == OrderStatus.FILLED

    def test_recomputes_weighted_average_fill_price_on_partial_completion(self):
        order = _order(
            quantity=Decimal("1"), status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("0.4"), average_fill_price=Decimal("100"),
        )
        result = FillEngine.execute_market_order(
            order, market_price=Decimal("200"), fee_rate=Decimal("0"),
            executed_at=_now(), execution_id="exec-2",
        )
        expected_average = ((Decimal("100") * Decimal("0.4")) + (Decimal("200") * Decimal("0.6"))) / Decimal("1")
        assert result.order.average_fill_price == expected_average

    def test_original_order_is_not_mutated(self):
        order = _order(quantity=Decimal("0.1"))
        original_status = order.status
        original_filled = order.filled_quantity
        FillEngine.execute_market_order(
            order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            executed_at=_now(), execution_id="exec-1",
        )
        assert order.status == original_status
        assert order.filled_quantity == original_filled

    def test_same_input_produces_same_output(self):
        order = _order(quantity=Decimal("0.1"))
        executed_at = _now()
        result1 = FillEngine.execute_market_order(
            order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            executed_at=executed_at, execution_id="exec-1",
        )
        result2 = FillEngine.execute_market_order(
            order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            executed_at=executed_at, execution_id="exec-1",
        )
        assert result1.order == result2.order
        assert result1.execution == result2.execution


class TestExecuteMarketOrderRejections:
    def test_rejects_limit_order_type(self):
        order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        with pytest.raises(InvalidOrderTransitionError):
            FillEngine.execute_market_order(
                order, market_price=Decimal("100"), fee_rate=Decimal("0"),
                executed_at=_now(), execution_id="exec-1",
            )

    @pytest.mark.parametrize("status", [
        OrderStatus.NEW, OrderStatus.FILLED, OrderStatus.CANCELLED,
        OrderStatus.REJECTED, OrderStatus.EXPIRED,
    ])
    def test_rejects_unfillable_statuses(self, status):
        order = _order(status=status)
        if status in (OrderStatus.FILLED,):
            order = _order(status=status, filled_quantity=Decimal("0.1"), average_fill_price=Decimal("100"))
        with pytest.raises(InvalidOrderTransitionError):
            FillEngine.execute_market_order(
                order, market_price=Decimal("100"), fee_rate=Decimal("0"),
                executed_at=_now(), execution_id="exec-1",
            )

    def test_rejects_zero_market_price(self):
        order = _order()
        with pytest.raises(ValueError):
            FillEngine.execute_market_order(
                order, market_price=Decimal("0"), fee_rate=Decimal("0"),
                executed_at=_now(), execution_id="exec-1",
            )

    def test_rejects_negative_market_price(self):
        order = _order()
        with pytest.raises(ValueError):
            FillEngine.execute_market_order(
                order, market_price=Decimal("-1"), fee_rate=Decimal("0"),
                executed_at=_now(), execution_id="exec-1",
            )

    def test_rejects_negative_fee_rate(self):
        order = _order()
        with pytest.raises(ValueError):
            FillEngine.execute_market_order(
                order, market_price=Decimal("100"), fee_rate=Decimal("-0.001"),
                executed_at=_now(), execution_id="exec-1",
            )

    def test_rejects_zero_remaining_quantity(self):
        """PARTIALLY_FILLED con filled_quantity == quantity: no debería existir en la
        práctica, pero el motor debe rechazarlo explícitamente en vez de generar
        una Execution de cantidad 0."""
        order = _order(
            quantity=Decimal("1"), status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("1"), average_fill_price=Decimal("100"),
        )
        with pytest.raises(OverFillError):
            FillEngine.execute_market_order(
                order, market_price=Decimal("100"), fee_rate=Decimal("0"),
                executed_at=_now(), execution_id="exec-1",
            )
