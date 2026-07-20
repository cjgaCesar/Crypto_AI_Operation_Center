"""
Pruebas para PositionEngine (Etapa 6.2): aplicar una Execution sobre una Position.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide
from src.paper_trading.exceptions import OverFillError, PaperTradingDomainError
from src.paper_trading.models import Execution, Order, Position
from src.paper_trading.position_engine import PositionEngine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(side: OrderSide, **overrides) -> Order:
    quantity = overrides.get("quantity", Decimal("0.1"))
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT",
        side=side, order_type=OrderType.MARKET,
        quantity=quantity, status=OrderStatus.FILLED,
        filled_quantity=quantity, average_fill_price=Decimal("50000"),
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _execution(**overrides) -> Execution:
    defaults = dict(
        id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
        quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"),
        executed_at=_now(),
    )
    defaults.update(overrides)
    return Execution(**defaults)


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


class TestApplyExecutionBuy:
    def test_opens_long_from_flat(self):
        position = _flat_position()
        order = _order(OrderSide.BUY)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        result = PositionEngine.apply_execution(position, order, execution, _now())
        assert result.position.side == PositionSide.LONG
        assert result.position.quantity == Decimal("0.1")
        assert result.position.average_entry_price == Decimal("50000")
        assert result.position.opened_at == execution.executed_at

    def test_buy_never_generates_a_trade(self):
        position = _flat_position()
        order = _order(OrderSide.BUY)
        execution = _execution()
        result = PositionEngine.apply_execution(position, order, execution, _now())
        assert result.trade is None
        assert result.closed_quantity == Decimal("0")
        assert result.gross_realized_pnl == Decimal("0")

    def test_realized_pnl_to_date_unchanged_on_buy(self):
        position = _long_position(realized_pnl_to_date=Decimal("42"))
        order = _order(OrderSide.BUY)
        execution = _execution(quantity=Decimal("0.05"), price=Decimal("52000"))
        result = PositionEngine.apply_execution(position, order, execution, _now())
        assert result.position.realized_pnl_to_date == Decimal("42")

    def test_increases_long_with_weighted_average(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.BUY, quantity=Decimal("0.05"))
        execution = _execution(quantity=Decimal("0.05"), price=Decimal("52000"))
        result = PositionEngine.apply_execution(position, order, execution, _now())
        expected_quantity = Decimal("0.15")
        expected_average = (
            (Decimal("0.1") * Decimal("50000")) + (Decimal("0.05") * Decimal("52000"))
        ) / expected_quantity
        assert result.position.quantity == expected_quantity
        assert result.position.average_entry_price == expected_average
        assert result.position.side == PositionSide.LONG

    def test_increase_preserves_original_opened_at(self):
        opened_at = _now() - timedelta(days=1)
        position = _long_position(opened_at=opened_at)
        order = _order(OrderSide.BUY, quantity=Decimal("0.05"))
        execution = _execution(quantity=Decimal("0.05"), price=Decimal("52000"))
        result = PositionEngine.apply_execution(position, order, execution, _now())
        assert result.position.opened_at == opened_at

    def test_original_position_and_execution_not_mutated(self):
        position = _flat_position()
        order = _order(OrderSide.BUY)
        execution = _execution()
        original_side = position.side
        original_quantity = position.quantity
        PositionEngine.apply_execution(position, order, execution, _now())
        assert position.side == original_side
        assert position.quantity == original_quantity


class TestApplyExecutionSell:
    def test_reduces_long_partially(self):
        position = _long_position(quantity=Decimal("0.15"), average_entry_price=Decimal("50666.67"))
        order = _order(OrderSide.SELL, quantity=Decimal("0.05"))
        execution = _execution(quantity=Decimal("0.05"), price=Decimal("53000"), fee=Decimal("2.65"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.position.side == PositionSide.LONG
        assert result.position.quantity == Decimal("0.10")
        assert result.position.average_entry_price == Decimal("50666.67")
        assert result.trade is not None
        assert result.trade.quantity == Decimal("0.05")

    def test_closes_long_completely(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), opened_at=_now())
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("54000"), fee=Decimal("5.4"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.position.side == PositionSide.FLAT
        assert result.position.quantity == Decimal("0")
        assert result.position.average_entry_price is None
        assert result.position.opened_at is None

    def test_gross_pnl_positive(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("54000"), fee=Decimal("0"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.gross_realized_pnl == Decimal("400")
        assert result.trade.gross_pnl == Decimal("400")

    def test_gross_pnl_negative(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("48000"), fee=Decimal("0"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.gross_realized_pnl == Decimal("-200")

    def test_gross_pnl_zero(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("0"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.gross_realized_pnl == Decimal("0")

    def test_closing_fee_is_exactly_execution_fee(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("54000"), fee=Decimal("5.4"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.trade.fees == Decimal("5.4")

    def test_net_pnl_is_gross_minus_fees(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("54000"), fee=Decimal("5.4"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.trade.net_pnl == result.trade.gross_pnl - result.trade.fees
        assert result.trade.net_pnl == Decimal("394.6")

    def test_realized_pnl_to_date_accumulates_net_pnl(self):
        position = _long_position(
            quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), realized_pnl_to_date=Decimal("100"),
        )
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("54000"), fee=Decimal("5.4"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.position.realized_pnl_to_date == Decimal("100") + Decimal("394.6")

    def test_sell_on_flat_position_is_rejected(self):
        position = _flat_position()
        order = _order(OrderSide.SELL)
        execution = _execution()
        with pytest.raises(PaperTradingDomainError):
            PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")

    def test_sell_greater_than_available_quantity_is_rejected(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL, quantity=Decimal("0.2"))
        execution = _execution(quantity=Decimal("0.2"), price=Decimal("50000"))
        with pytest.raises(OverFillError):
            PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")

    def test_sell_reduce_respects_reserved_quantity(self):
        """execution.quantity no puede superar available_quantity (quantity - reserved_quantity)."""
        position = _long_position(
            quantity=Decimal("0.1"), reserved_quantity=Decimal("0.05"), average_entry_price=Decimal("50000"),
        )
        order = _order(OrderSide.SELL, quantity=Decimal("0.06"))
        execution = _execution(quantity=Decimal("0.06"), price=Decimal("50000"))
        with pytest.raises(OverFillError):
            PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")

    def test_missing_trade_id_is_rejected(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        with pytest.raises(ValueError):
            PositionEngine.apply_execution(position, order, execution, _now(), trade_id=None)

    def test_trade_side_is_long(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        result = PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert result.trade.side == TradeSide.LONG

    def test_original_position_not_mutated(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        original_quantity = position.quantity
        order = _order(OrderSide.SELL)
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        PositionEngine.apply_execution(position, order, execution, _now(), trade_id="trade-1")
        assert position.quantity == original_quantity
        assert position.side == PositionSide.LONG


class TestApplyExecutionShort:
    def test_short_position_is_rejected(self):
        position = _long_position(side=PositionSide.SHORT, quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        order = _order(OrderSide.BUY)
        execution = _execution()
        with pytest.raises(PaperTradingDomainError):
            PositionEngine.apply_execution(position, order, execution, _now())
