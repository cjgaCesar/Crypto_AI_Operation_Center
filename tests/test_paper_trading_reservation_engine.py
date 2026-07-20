"""
Pruebas para ReservationEngine (Etapa 6.7): reserva y liberación de
recursos al aceptar/llenar/cancelar una orden.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.exceptions import (
    InsufficientReservedCashError, InsufficientReservedQuantityError,
    InvalidOrderStateError, PaperTradingDomainError, ReservationAlreadyReleasedError, ReservationNotFoundError,
)
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.reservation_engine import ReservationEngine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(side: OrderSide = OrderSide.BUY, **overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=side,
        order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.NEW,
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


def _flat_position(**overrides) -> Position:
    defaults = dict(exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now())
    defaults.update(overrides)
    return Position(**defaults)


def _long_position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestReserveForOrderBuy:
    def test_reserves_notional_plus_fee(self, ):
        order = _order(quantity=Decimal("0.1"))
        cash = _cash_balance()
        position = _flat_position()

        result = ReservationEngine.reserve_for_order(order, cash, position, Decimal("50000"), Decimal("0.001"), _now())

        assert result.order.reserved_notional == Decimal("5000")
        assert result.order.reserved_fee == Decimal("5")
        assert result.cash_balance.reserved_balance == Decimal("5005")

    def test_does_not_change_total_balance(self):
        order = _order()
        cash = _cash_balance(total_balance=Decimal("10000"))
        position = _flat_position()
        result = ReservationEngine.reserve_for_order(order, cash, position, Decimal("50000"), Decimal("0.001"), _now())
        assert result.cash_balance.total_balance == Decimal("10000")

    def test_available_balance_decreases(self):
        order = _order()
        cash = _cash_balance(total_balance=Decimal("10000"))
        position = _flat_position()
        result = ReservationEngine.reserve_for_order(order, cash, position, Decimal("50000"), Decimal("0.001"), _now())
        assert result.cash_balance.available_balance == Decimal("4995")

    def test_order_status_becomes_pending(self):
        order = _order()
        result = ReservationEngine.reserve_for_order(order, _cash_balance(), _flat_position(), Decimal("50000"), Decimal("0.001"), _now())
        assert result.order.status == OrderStatus.PENDING
        assert result.order.reserved_price == Decimal("50000")

    def test_insufficient_cash_raises(self):
        order = _order(quantity=Decimal("100"))
        cash = _cash_balance(total_balance=Decimal("100"))
        with pytest.raises(InsufficientReservedCashError):
            ReservationEngine.reserve_for_order(order, cash, _flat_position(), Decimal("50000"), Decimal("0.001"), _now())

    def test_decimal_exact(self):
        order = _order(quantity=Decimal("0.00000001"))
        cash = _cash_balance()
        result = ReservationEngine.reserve_for_order(order, cash, _flat_position(), Decimal("123456789.123456789"), Decimal("0.001"), _now())
        expected_notional = Decimal("0.00000001") * Decimal("123456789.123456789")
        assert result.order.reserved_notional == expected_notional

    def test_does_not_mutate_inputs(self):
        order = _order()
        cash = _cash_balance()
        position = _flat_position()
        original_cash_reserved = cash.reserved_balance
        original_order_status = order.status
        ReservationEngine.reserve_for_order(order, cash, position, Decimal("50000"), Decimal("0.001"), _now())
        assert cash.reserved_balance == original_cash_reserved
        assert order.status == original_order_status

    def test_position_unchanged_for_buy(self):
        order = _order()
        position = _flat_position()
        result = ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("50000"), Decimal("0.001"), _now())
        assert result.position == position


class TestReserveForOrderSell:
    def test_reserves_quantity(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        position = _long_position(quantity=Decimal("0.1"))
        result = ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("54000"), Decimal("0.001"), _now())
        assert result.order.reserved_quantity == Decimal("0.05")
        assert result.position.reserved_quantity == Decimal("0.05")

    def test_quantity_unchanged(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        position = _long_position(quantity=Decimal("0.1"))
        result = ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("54000"), Decimal("0.001"), _now())
        assert result.position.quantity == Decimal("0.1")

    def test_available_quantity_decreases(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        position = _long_position(quantity=Decimal("0.1"))
        result = ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("54000"), Decimal("0.001"), _now())
        assert result.position.available_quantity == Decimal("0.05")

    def test_position_does_not_exist_raises(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        position = _flat_position()
        with pytest.raises(InsufficientReservedQuantityError):
            ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("54000"), Decimal("0.001"), _now())

    def test_flat_position_raises(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        with pytest.raises(InsufficientReservedQuantityError):
            ReservationEngine.reserve_for_order(order, _cash_balance(), _flat_position(), Decimal("54000"), Decimal("0.001"), _now())

    def test_insufficient_quantity_raises(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.5"))
        position = _long_position(quantity=Decimal("0.1"))
        with pytest.raises(InsufficientReservedQuantityError):
            ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("54000"), Decimal("0.001"), _now())

    def test_does_not_mutate_inputs(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        position = _long_position(quantity=Decimal("0.1"))
        original_reserved = position.reserved_quantity
        ReservationEngine.reserve_for_order(order, _cash_balance(), position, Decimal("54000"), Decimal("0.001"), _now())
        assert position.reserved_quantity == original_reserved

    def test_cash_balance_unchanged_for_sell(self):
        order = _order(side=OrderSide.SELL, quantity=Decimal("0.05"))
        position = _long_position(quantity=Decimal("0.1"))
        cash = _cash_balance()
        result = ReservationEngine.reserve_for_order(order, cash, position, Decimal("54000"), Decimal("0.001"), _now())
        assert result.cash_balance == cash


class TestReserveForOrderCommon:
    def test_rejects_non_new_status(self):
        order = _order(status=OrderStatus.PENDING, reserved_price=Decimal("50000"), reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"))
        with pytest.raises(InvalidOrderStateError):
            ReservationEngine.reserve_for_order(order, _cash_balance(), _flat_position(), Decimal("50000"), Decimal("0.001"), _now())

    def test_rejects_zero_market_price(self):
        with pytest.raises(ValueError):
            ReservationEngine.reserve_for_order(_order(), _cash_balance(), _flat_position(), Decimal("0"), Decimal("0.001"), _now())

    def test_rejects_negative_fee_rate(self):
        with pytest.raises(ValueError):
            ReservationEngine.reserve_for_order(_order(), _cash_balance(), _flat_position(), Decimal("50000"), Decimal("-0.001"), _now())

    def test_rejects_short_position(self):
        position = _long_position(side=PositionSide.SHORT)
        with pytest.raises(PaperTradingDomainError):
            ReservationEngine.reserve_for_order(_order(), _cash_balance(), position, Decimal("50000"), Decimal("0.001"), _now())


class TestReleaseForOrderBuy:
    def _accepted_order(self, **overrides):
        defaults = dict(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        defaults.update(overrides)
        return _order(**defaults)

    def test_releases_notional_plus_fee(self):
        order = self._accepted_order()
        cash = _cash_balance(reserved_balance=Decimal("5005"))
        result = ReservationEngine.release_for_order(order, cash, _flat_position(), _now())
        assert result.cash_balance.reserved_balance == Decimal("0")

    def test_never_goes_negative(self):
        order = self._accepted_order()
        cash = _cash_balance(reserved_balance=Decimal("1"))
        with pytest.raises(ReservationAlreadyReleasedError):
            ReservationEngine.release_for_order(order, cash, _flat_position(), _now())

    def test_missing_reservation_data_raises(self):
        order = _order(status=OrderStatus.PENDING, reserved_price=Decimal("50000"))
        with pytest.raises(ReservationNotFoundError):
            ReservationEngine.release_for_order(order, _cash_balance(reserved_balance=Decimal("100")), _flat_position(), _now())

    def test_timestamp_is_exact(self):
        fixed_time = datetime(2030, 1, 1, tzinfo=timezone.utc)
        order = self._accepted_order()
        cash = _cash_balance(reserved_balance=Decimal("5005"))
        result = ReservationEngine.release_for_order(order, cash, _flat_position(), fixed_time)
        assert result.cash_balance.updated_at == fixed_time

    def test_does_not_mutate_inputs(self):
        order = self._accepted_order()
        cash = _cash_balance(reserved_balance=Decimal("5005"))
        original_reserved = cash.reserved_balance
        ReservationEngine.release_for_order(order, cash, _flat_position(), _now())
        assert cash.reserved_balance == original_reserved


class TestReleaseForOrderSell:
    def _accepted_order(self, **overrides):
        defaults = dict(side=OrderSide.SELL, status=OrderStatus.PENDING, reserved_price=Decimal("54000"), reserved_quantity=Decimal("0.05"))
        defaults.update(overrides)
        return _order(**defaults)

    def test_releases_quantity(self):
        order = self._accepted_order()
        position = _long_position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.05"))
        result = ReservationEngine.release_for_order(order, _cash_balance(), position, _now())
        assert result.position.reserved_quantity == Decimal("0")

    def test_never_goes_negative(self):
        order = self._accepted_order()
        position = _long_position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.01"))
        with pytest.raises(ReservationAlreadyReleasedError):
            ReservationEngine.release_for_order(order, _cash_balance(), position, _now())

    def test_missing_reservation_data_raises(self):
        order = _order(side=OrderSide.SELL, status=OrderStatus.PENDING, reserved_price=Decimal("54000"))
        position = _long_position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.05"))
        with pytest.raises(ReservationNotFoundError):
            ReservationEngine.release_for_order(order, _cash_balance(), position, _now())

    def test_cash_balance_unchanged(self):
        order = self._accepted_order()
        position = _long_position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.05"))
        cash = _cash_balance()
        result = ReservationEngine.release_for_order(order, cash, position, _now())
        assert result.cash_balance == cash


class TestReleaseForOrderCommon:
    def test_rejects_non_pending_status(self):
        order = _order(status=OrderStatus.NEW)
        with pytest.raises(InvalidOrderStateError):
            ReservationEngine.release_for_order(order, _cash_balance(), _flat_position(), _now())

    def test_rejects_already_filled_order(self):
        order = _order(
            status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"), average_fill_price=Decimal("50000"),
            reserved_price=Decimal("50000"), reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        with pytest.raises(InvalidOrderStateError):
            ReservationEngine.release_for_order(order, _cash_balance(), _flat_position(), _now())
