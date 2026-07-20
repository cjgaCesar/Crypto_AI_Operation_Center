"""
Pruebas para RiskEngine (Etapa 6.2): validación previa a aceptar una orden.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.risk_engine import RiskEngine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(side: OrderSide, **overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT",
        side=side, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.NEW,
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _flat_position(**overrides) -> Position:
    defaults = dict(exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now())
    defaults.update(overrides)
    return Position(**defaults)


def _long_position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"),
        opened_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


def _validate(order, cash_balance=None, position=None, **overrides):
    kwargs = dict(
        order=order,
        cash_balance=cash_balance or _cash_balance(),
        position=position or _flat_position(),
        market_price=Decimal("50000"),
        max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"),
        fee_rate=Decimal("0.001"),
        timestamp=_now(),
        rules_version="v1",
    )
    kwargs.update(overrides)
    return RiskEngine.validate_order(**kwargs)


class TestValidateOrderApproved:
    def test_buy_within_limits_is_approved(self):
        order = _order(OrderSide.BUY, quantity=Decimal("0.1"))
        result = _validate(order)
        assert result.approved is True
        assert result.code == "APPROVED"

    def test_sell_within_available_quantity_is_approved(self):
        order = _order(OrderSide.SELL, quantity=Decimal("0.05"))
        position = _long_position(quantity=Decimal("0.1"))
        result = _validate(order, position=position)
        assert result.approved is True
        assert result.code == "APPROVED"

    def test_approved_result_has_full_metadata(self):
        order = _order(OrderSide.BUY, quantity=Decimal("0.1"))
        result = _validate(order, rules_version="v42")
        assert result.message
        assert result.metrics_used
        assert result.limits_used
        assert result.timestamp is not None
        assert result.rules_version == "v42"

    def test_value_exactly_at_max_order_value_is_approved(self):
        order = _order(OrderSide.BUY, quantity=Decimal("2"))
        result = _validate(order, market_price=Decimal("100"), max_order_value=Decimal("200"), fee_rate=Decimal("0"))
        assert result.approved is True

    def test_value_exactly_at_max_position_value_is_approved(self):
        order = _order(OrderSide.BUY, quantity=Decimal("2"))
        result = _validate(
            order, market_price=Decimal("100"), max_order_value=Decimal("1000"),
            max_position_value=Decimal("200"), fee_rate=Decimal("0"),
        )
        assert result.approved is True

    def test_required_cash_exactly_at_available_balance_is_approved(self):
        order = _order(OrderSide.BUY, quantity=Decimal("1"))
        cash = _cash_balance(total_balance=Decimal("100"))
        result = _validate(order, cash_balance=cash, market_price=Decimal("100"), fee_rate=Decimal("0"))
        assert result.approved is True


class TestValidateOrderRejections:
    def test_limit_order_is_rejected(self):
        order = _order(OrderSide.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        result = _validate(order)
        assert result.approved is False
        assert result.code == "ORDER_TYPE_UNSUPPORTED"

    def test_non_new_status_is_rejected(self):
        order = _order(OrderSide.BUY, status=OrderStatus.PENDING)
        result = _validate(order)
        assert result.approved is False
        assert result.code == "ORDER_STATUS_INVALID"

    def test_short_position_is_rejected(self):
        order = _order(OrderSide.BUY)
        position = _long_position(side=PositionSide.SHORT)
        result = _validate(order, position=position)
        assert result.approved is False
        assert result.code == "POSITION_SIDE_UNSUPPORTED"

    def test_sell_without_position_is_rejected(self):
        order = _order(OrderSide.SELL, quantity=Decimal("0.1"))
        result = _validate(order, position=_flat_position())
        assert result.approved is False
        assert result.code == "SELL_WITHOUT_POSITION"

    def test_sell_greater_than_available_is_rejected(self):
        order = _order(OrderSide.SELL, quantity=Decimal("0.2"))
        position = _long_position(quantity=Decimal("0.1"))
        result = _validate(order, position=position)
        assert result.approved is False
        assert result.code == "INSUFFICIENT_AVAILABLE_QUANTITY"

    def test_insufficient_cash_is_rejected(self):
        order = _order(OrderSide.BUY, quantity=Decimal("1"))
        cash = _cash_balance(total_balance=Decimal("10"))
        result = _validate(order, cash_balance=cash, market_price=Decimal("50000"))
        assert result.approved is False
        assert result.code == "INSUFFICIENT_AVAILABLE_CASH"

    def test_order_exceeding_max_order_value_is_rejected(self):
        order = _order(OrderSide.BUY, quantity=Decimal("1"))
        result = _validate(order, market_price=Decimal("100"), max_order_value=Decimal("50"), fee_rate=Decimal("0"))
        assert result.approved is False
        assert result.code == "MAX_ORDER_VALUE_EXCEEDED"

    def test_position_exceeding_max_position_value_is_rejected(self):
        order = _order(OrderSide.BUY, quantity=Decimal("1"))
        position = _long_position(quantity=Decimal("2"), average_entry_price=Decimal("100"))
        result = _validate(
            order, position=position, market_price=Decimal("100"),
            max_order_value=Decimal("1000"), max_position_value=Decimal("250"), fee_rate=Decimal("0"),
        )
        assert result.approved is False
        assert result.code == "MAX_POSITION_VALUE_EXCEEDED"

    def test_rejected_result_has_full_metadata(self):
        order = _order(OrderSide.BUY, quantity=Decimal("1"))
        cash = _cash_balance(total_balance=Decimal("10"))
        result = _validate(order, cash_balance=cash, market_price=Decimal("50000"))
        assert result.message
        assert result.metrics_used
        assert result.limits_used
        assert result.timestamp is not None
        assert result.rules_version


class TestValidateOrderPrecedence:
    def test_type_error_takes_precedence_over_status_error(self):
        """LIMIT + estado inválido: debe reportarse el error de tipo primero."""
        order = _order(
            OrderSide.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100"),
            status=OrderStatus.PENDING,
        )
        result = _validate(order)
        assert result.code == "ORDER_TYPE_UNSUPPORTED"

    def test_status_error_takes_precedence_over_position_side_error(self):
        order = _order(OrderSide.BUY, status=OrderStatus.PENDING)
        position = _long_position(side=PositionSide.SHORT)
        result = _validate(order, position=position)
        assert result.code == "ORDER_STATUS_INVALID"

    def test_position_side_error_takes_precedence_over_cash_error(self):
        order = _order(OrderSide.BUY, quantity=Decimal("100"))
        position = _long_position(side=PositionSide.SHORT)
        cash = _cash_balance(total_balance=Decimal("0"))
        result = _validate(order, cash_balance=cash, position=position, market_price=Decimal("50000"))
        assert result.code == "POSITION_SIDE_UNSUPPORTED"

    def test_cash_error_takes_precedence_over_max_order_value_error(self):
        order = _order(OrderSide.BUY, quantity=Decimal("10"))
        cash = _cash_balance(total_balance=Decimal("1"))
        result = _validate(
            order, cash_balance=cash, market_price=Decimal("50000"), max_order_value=Decimal("1"),
        )
        assert result.code == "INSUFFICIENT_AVAILABLE_CASH"

    def test_max_order_value_error_takes_precedence_over_max_position_value_error(self):
        order = _order(OrderSide.BUY, quantity=Decimal("10"))
        result = _validate(
            order, market_price=Decimal("100"), max_order_value=Decimal("50"),
            max_position_value=Decimal("1"), fee_rate=Decimal("0"),
        )
        assert result.code == "MAX_ORDER_VALUE_EXCEEDED"


class TestValidateOrderMisc:
    def test_fee_is_included_in_required_cash(self):
        order = _order(OrderSide.BUY, quantity=Decimal("1"))
        cash = _cash_balance(total_balance=Decimal("100"))
        result = _validate(order, cash_balance=cash, market_price=Decimal("100"), fee_rate=Decimal("0.5"))
        assert result.approved is False
        assert result.code == "INSUFFICIENT_AVAILABLE_CASH"

    def test_rejects_zero_market_price(self):
        order = _order(OrderSide.BUY)
        with pytest.raises(ValueError):
            _validate(order, market_price=Decimal("0"))

    def test_rejects_negative_fee_rate(self):
        order = _order(OrderSide.BUY)
        with pytest.raises(ValueError):
            _validate(order, fee_rate=Decimal("-0.01"))

    def test_no_exception_is_raised_for_a_normal_rejection(self):
        order = _order(OrderSide.SELL, quantity=Decimal("0.1"))
        result = _validate(order, position=_flat_position())
        assert isinstance(result.approved, bool)

    def test_inputs_not_mutated(self):
        order = _order(OrderSide.BUY, quantity=Decimal("0.1"))
        cash = _cash_balance()
        position = _flat_position()
        original_status = order.status
        original_cash = cash.total_balance
        _validate(order, cash_balance=cash, position=position)
        assert order.status == original_status
        assert cash.total_balance == original_cash

    def test_same_input_produces_same_output(self):
        order = _order(OrderSide.BUY, quantity=Decimal("0.1"))
        timestamp = _now()
        result1 = _validate(order, timestamp=timestamp)
        result2 = _validate(order, timestamp=timestamp)
        assert result1 == result2
