"""
Pruebas para PnLEngine (Etapa 6.2): PnL no realizado, valor de posición y snapshots.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import PositionSide
from src.paper_trading.exceptions import PaperTradingDomainError
from src.paper_trading.models import CashBalance, Position
from src.paper_trading.pnl_engine import PnLEngine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _long_position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"),
        opened_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


def _flat_position(**overrides) -> Position:
    defaults = dict(exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now())
    defaults.update(overrides)
    return Position(**defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


class TestCalculateUnrealizedPnl:
    def test_positive_pnl_for_long(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        pnl = PnLEngine.calculate_unrealized_pnl(position, Decimal("51000"))
        assert pnl == Decimal("100")

    def test_negative_pnl_for_long(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        pnl = PnLEngine.calculate_unrealized_pnl(position, Decimal("49000"))
        assert pnl == Decimal("-100")

    def test_zero_pnl_when_price_unchanged(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        pnl = PnLEngine.calculate_unrealized_pnl(position, Decimal("50000"))
        assert pnl == Decimal("0")

    def test_flat_position_has_zero_unrealized_pnl(self):
        position = _flat_position()
        pnl = PnLEngine.calculate_unrealized_pnl(position, Decimal("50000"))
        assert pnl == Decimal("0")

    def test_rejects_zero_price_for_long(self):
        position = _long_position()
        with pytest.raises(ValueError):
            PnLEngine.calculate_unrealized_pnl(position, Decimal("0"))

    def test_rejects_negative_price_for_long(self):
        position = _long_position()
        with pytest.raises(ValueError):
            PnLEngine.calculate_unrealized_pnl(position, Decimal("-1"))

    def test_rejects_short_position(self):
        position = _long_position(side=PositionSide.SHORT)
        with pytest.raises(PaperTradingDomainError):
            PnLEngine.calculate_unrealized_pnl(position, Decimal("50000"))

    def test_inputs_not_mutated(self):
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        original_quantity = position.quantity
        PnLEngine.calculate_unrealized_pnl(position, Decimal("51000"))
        assert position.quantity == original_quantity


class TestCalculatePositionValue:
    def test_long_position_value(self):
        position = _long_position(quantity=Decimal("0.1"))
        value = PnLEngine.calculate_position_value(position, Decimal("50000"))
        assert value == Decimal("5000")

    def test_flat_position_value_is_zero(self):
        position = _flat_position()
        value = PnLEngine.calculate_position_value(position, Decimal("50000"))
        assert value == Decimal("0")

    def test_rejects_short_position(self):
        position = _long_position(side=PositionSide.SHORT)
        with pytest.raises(PaperTradingDomainError):
            PnLEngine.calculate_position_value(position, Decimal("50000"))


class TestBuildPnlSnapshot:
    def test_snapshot_per_symbol(self):
        position = _long_position(
            exchange="Binance", symbol="ETHUSDT", quantity=Decimal("1"),
            average_entry_price=Decimal("2000"), realized_pnl_to_date=Decimal("50"),
        )
        timestamp = _now()
        snapshot = PnLEngine.build_pnl_snapshot(position, Decimal("2100"), timestamp)
        assert snapshot.exchange == "Binance"
        assert snapshot.symbol == "ETHUSDT"
        assert snapshot.timestamp == timestamp
        assert snapshot.position_quantity == Decimal("1")
        assert snapshot.unrealized_pnl == Decimal("100")
        assert snapshot.realized_pnl_cumulative == Decimal("50")

    def test_snapshot_for_flat_position(self):
        position = _flat_position(realized_pnl_to_date=Decimal("300"))
        snapshot = PnLEngine.build_pnl_snapshot(position, Decimal("50000"), _now())
        assert snapshot.position_quantity == Decimal("0")
        assert snapshot.unrealized_pnl == Decimal("0")
        assert snapshot.realized_pnl_cumulative == Decimal("300")


class TestBuildPortfolioSnapshot:
    def test_portfolio_with_single_position(self):
        cash = _cash_balance(total_balance=Decimal("5000"))
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        prices = {("Binance", "BTCUSDT"): Decimal("51000")}
        snapshot = PnLEngine.build_portfolio_snapshot(cash, [position], prices, _now())
        assert snapshot.cash_balance == Decimal("5000")
        assert snapshot.positions_value == Decimal("5100")
        assert snapshot.total_equity == Decimal("10100")
        assert snapshot.unrealized_pnl_total == Decimal("100")

    def test_portfolio_with_multiple_positions(self):
        cash = _cash_balance(total_balance=Decimal("1000"))
        btc = _long_position(exchange="Binance", symbol="BTCUSDT", quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        eth = _long_position(exchange="Binance", symbol="ETHUSDT", quantity=Decimal("1"), average_entry_price=Decimal("2000"))
        prices = {("Binance", "BTCUSDT"): Decimal("51000"), ("Binance", "ETHUSDT"): Decimal("2100")}
        snapshot = PnLEngine.build_portfolio_snapshot(cash, [btc, eth], prices, _now())
        assert snapshot.positions_value == Decimal("5100") + Decimal("2100")
        assert snapshot.unrealized_pnl_total == Decimal("100") + Decimal("100")

    def test_realized_pnl_cumulative_sums_all_positions(self):
        cash = _cash_balance()
        btc = _long_position(exchange="Binance", symbol="BTCUSDT", realized_pnl_to_date=Decimal("50"))
        closed = _flat_position(exchange="Binance", symbol="ETHUSDT", realized_pnl_to_date=Decimal("30"))
        prices = {("Binance", "BTCUSDT"): Decimal("51000")}
        snapshot = PnLEngine.build_portfolio_snapshot(cash, [btc, closed], prices, _now())
        assert snapshot.realized_pnl_cumulative == Decimal("80")

    def test_total_equity_matches_cash_plus_positions_value(self):
        cash = _cash_balance(total_balance=Decimal("2000"))
        position = _long_position(quantity=Decimal("1"), average_entry_price=Decimal("100"))
        prices = {("Binance", "BTCUSDT"): Decimal("110")}
        snapshot = PnLEngine.build_portfolio_snapshot(cash, [position], prices, _now())
        assert snapshot.total_equity == snapshot.cash_balance + snapshot.positions_value

    def test_missing_price_for_open_position_raises(self):
        cash = _cash_balance()
        position = _long_position()
        with pytest.raises(ValueError):
            PnLEngine.build_portfolio_snapshot(cash, [position], {}, _now())

    def test_flat_position_does_not_require_price(self):
        cash = _cash_balance()
        position = _flat_position()
        snapshot = PnLEngine.build_portfolio_snapshot(cash, [position], {}, _now())
        assert snapshot.positions_value == Decimal("0")

    def test_rejects_short_position(self):
        cash = _cash_balance()
        position = _long_position(side=PositionSide.SHORT)
        with pytest.raises(PaperTradingDomainError):
            PnLEngine.build_portfolio_snapshot(cash, [position], {("Binance", "BTCUSDT"): Decimal("100")}, _now())

    def test_inputs_not_mutated(self):
        cash = _cash_balance(total_balance=Decimal("5000"))
        position = _long_position(quantity=Decimal("0.1"), average_entry_price=Decimal("50000"))
        original_total_balance = cash.total_balance
        original_quantity = position.quantity
        PnLEngine.build_portfolio_snapshot(cash, [position], {("Binance", "BTCUSDT"): Decimal("51000")}, _now())
        assert cash.total_balance == original_total_balance
        assert position.quantity == original_quantity
