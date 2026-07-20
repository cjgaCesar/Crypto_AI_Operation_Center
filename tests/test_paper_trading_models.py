"""
Pruebas para los modelos de dominio de Paper Trading (Etapa 6.1).

Cubre: creación válida/inválida, enums, invariantes declarativos y
cruzados, serialización/deserialización (dict y JSON), datetime y
Decimal. No hay pruebas de integración: el dominio no depende de
SQLite/Streamlit/Binance todavía (ver src/paper_trading/__init__.py).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.paper_trading.enums import (
    OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide,
)
from src.paper_trading.models import (
    CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, RiskValidationResult, Trade,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(**overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT",
        side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.NEW,
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


def _trade(**overrides) -> Trade:
    opened = _now()
    defaults = dict(
        id="trade-1", exchange="Binance", symbol="BTCUSDT", side=TradeSide.LONG,
        quantity=Decimal("0.05"), entry_price=Decimal("50666.67"), exit_price=Decimal("53000"),
        gross_pnl=Decimal("116.67"), fees=Decimal("2.65"), net_pnl=Decimal("114.02"),
        opened_at=opened, closed_at=opened + timedelta(minutes=5),
        exit_execution_id="exec-2",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def _position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"),
        updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


def _portfolio_snapshot(**overrides) -> PortfolioSnapshot:
    defaults = dict(
        timestamp=_now(), cash_balance=Decimal("5000"), positions_value=Decimal("5000"),
        total_equity=Decimal("10000"), unrealized_pnl_total=Decimal("0"),
        realized_pnl_cumulative=Decimal("0"),
    )
    defaults.update(overrides)
    return PortfolioSnapshot(**defaults)


def _pnl_snapshot(**overrides) -> PnLSnapshot:
    defaults = dict(
        timestamp=_now(), exchange="Binance", symbol="BTCUSDT",
        position_quantity=Decimal("0.1"), unrealized_pnl=Decimal("50"),
        realized_pnl_cumulative=Decimal("100"),
    )
    defaults.update(overrides)
    return PnLSnapshot(**defaults)


def _risk_result(**overrides) -> RiskValidationResult:
    defaults = dict(
        approved=True, code="OK", message="Orden dentro de los límites de riesgo.",
        metrics_used={"available_balance": Decimal("4995")},
        limits_used={"max_order_quantity": Decimal("1")},
        timestamp=_now(), rules_version="v1",
    )
    defaults.update(overrides)
    return RiskValidationResult(**defaults)


# --- Enums -------------------------------------------------------------------

class TestEnums:
    def test_order_side_values(self):
        assert {m.value for m in OrderSide} == {"BUY", "SELL"}

    def test_order_type_reserves_limit(self):
        assert {m.value for m in OrderType} == {"MARKET", "LIMIT"}

    def test_order_status_values(self):
        assert {m.value for m in OrderStatus} == {
            "NEW", "PENDING", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED",
        }

    def test_position_side_reserves_short(self):
        assert {m.value for m in PositionSide} == {"LONG", "FLAT", "SHORT"}

    def test_trade_side_reserves_short(self):
        assert {m.value for m in TradeSide} == {"LONG", "SHORT"}

    def test_order_source_reserves_strategy(self):
        assert {m.value for m in OrderSource} == {"MANUAL", "AI_RECOMMENDATION", "STRATEGY"}

    def test_enums_are_str_subclasses(self):
        assert isinstance(OrderSide.BUY, str)
        assert OrderSide.BUY == "BUY"


# --- Order ---------------------------------------------------------------

class TestOrder:
    def test_creates_valid_market_order(self):
        order = _order()
        assert order.quantity == Decimal("0.1")
        assert order.limit_price is None
        assert order.filled_quantity == Decimal("0")
        assert order.average_fill_price is None

    def test_rejects_zero_quantity(self):
        with pytest.raises(ValidationError):
            _order(quantity=Decimal("0"))

    def test_rejects_negative_quantity(self):
        with pytest.raises(ValidationError):
            _order(quantity=Decimal("-1"))

    def test_rejects_filled_quantity_greater_than_quantity(self):
        with pytest.raises(ValidationError):
            _order(
                quantity=Decimal("1"), filled_quantity=Decimal("2"),
                average_fill_price=Decimal("100"),
            )

    def test_accepts_filled_quantity_equal_to_quantity(self):
        order = _order(
            quantity=Decimal("1"), filled_quantity=Decimal("1"),
            average_fill_price=Decimal("100"), status=OrderStatus.FILLED,
        )
        assert order.filled_quantity == order.quantity

    def test_market_order_rejects_limit_price(self):
        with pytest.raises(ValidationError):
            _order(order_type=OrderType.MARKET, limit_price=Decimal("100"))

    def test_limit_order_requires_limit_price(self):
        with pytest.raises(ValidationError):
            _order(order_type=OrderType.LIMIT, limit_price=None)

    def test_limit_order_accepts_limit_price(self):
        order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        assert order.limit_price == Decimal("100")

    def test_average_fill_price_required_once_partially_filled(self):
        with pytest.raises(ValidationError):
            _order(
                status=OrderStatus.PARTIALLY_FILLED, filled_quantity=Decimal("0.05"),
                average_fill_price=None,
            )

    def test_average_fill_price_must_be_none_while_unfilled(self):
        with pytest.raises(ValidationError):
            _order(filled_quantity=Decimal("0"), average_fill_price=Decimal("100"))

    def test_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            _order(id="")

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            _order(symbol="")

    def test_cancelled_order_can_have_filled_quantity_greater_than_zero(self):
        """Cancelación tras ejecución parcial (ver ARQUITECTURA_PAPER_TRADING.md §4, casos especiales)."""
        order = _order(
            status=OrderStatus.CANCELLED, quantity=Decimal("1"),
            filled_quantity=Decimal("0.3"), average_fill_price=Decimal("50000"),
            cancellation_reason="Cancelación parcial del remanente.",
        )
        assert order.status == OrderStatus.CANCELLED
        assert order.filled_quantity == Decimal("0.3")

    def test_accepts_all_order_statuses(self):
        for status in OrderStatus:
            order = _order(status=status)
            assert order.status == status

    def test_reserved_quantity_does_not_apply_to_buy(self):
        """Etapa 6.7 (§21.2): reserved_quantity es solo para SELL."""
        with pytest.raises(ValidationError):
            _order(side=OrderSide.BUY, status=OrderStatus.PENDING, reserved_quantity=Decimal("0.1"))

    def test_reserved_notional_and_fee_do_not_apply_to_sell(self):
        with pytest.raises(ValidationError):
            _order(side=OrderSide.SELL, status=OrderStatus.PENDING, reserved_notional=Decimal("5000"))

    def test_reservation_fields_are_optional_and_default_to_none(self):
        order = _order()
        assert order.reserved_price is None
        assert order.reserved_notional is None
        assert order.reserved_fee is None
        assert order.reserved_quantity is None

    def test_accepts_populated_buy_reservation_fields(self):
        order = _order(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        assert order.reserved_notional == Decimal("5000")

    def test_accepts_populated_sell_reservation_fields(self):
        order = _order(
            side=OrderSide.SELL, status=OrderStatus.PENDING,
            reserved_price=Decimal("50000"), reserved_quantity=Decimal("0.1"),
        )
        assert order.reserved_quantity == Decimal("0.1")

    def test_accepts_ai_recommendation_source_with_linked_id(self):
        order = _order(source=OrderSource.AI_RECOMMENDATION, linked_recommendation_id="rec-1")
        assert order.linked_recommendation_id == "rec-1"

    def test_dict_round_trip(self):
        order = _order(filled_quantity=Decimal("0.05"), average_fill_price=Decimal("50000"))
        rebuilt = Order(**order.model_dump())
        assert rebuilt == order

    def test_json_round_trip_preserves_decimal_type(self):
        order = _order()
        rebuilt = Order.model_validate_json(order.model_dump_json())
        assert rebuilt == order
        assert isinstance(rebuilt.quantity, Decimal)

    def test_created_at_is_datetime(self):
        order = _order()
        assert isinstance(order.created_at, datetime)


# --- Execution -----------------------------------------------------------

class TestExecution:
    def test_creates_valid_execution(self):
        execution = _execution()
        assert execution.quantity == Decimal("0.1")
        assert execution.fee == Decimal("5")

    def test_rejects_zero_quantity(self):
        with pytest.raises(ValidationError):
            _execution(quantity=Decimal("0"))

    def test_rejects_zero_price(self):
        with pytest.raises(ValidationError):
            _execution(price=Decimal("0"))

    def test_rejects_negative_fee(self):
        with pytest.raises(ValidationError):
            _execution(fee=Decimal("-1"))

    def test_allows_zero_fee(self):
        execution = _execution(fee=Decimal("0"))
        assert execution.fee == Decimal("0")

    def test_dict_round_trip(self):
        execution = _execution()
        assert Execution(**execution.model_dump()) == execution


# --- Trade -----------------------------------------------------------------

class TestTrade:
    def test_creates_valid_trade(self):
        trade = _trade()
        assert trade.net_pnl == trade.gross_pnl - trade.fees

    def test_rejects_net_pnl_mismatch(self):
        with pytest.raises(ValidationError):
            _trade(gross_pnl=Decimal("100"), fees=Decimal("5"), net_pnl=Decimal("96"))

    def test_rejects_closed_before_opened(self):
        opened = _now()
        with pytest.raises(ValidationError):
            _trade(opened_at=opened, closed_at=opened - timedelta(minutes=1))

    def test_rejects_zero_quantity(self):
        with pytest.raises(ValidationError):
            _trade(quantity=Decimal("0"))

    def test_allows_zero_fees(self):
        trade = _trade(gross_pnl=Decimal("100"), fees=Decimal("0"), net_pnl=Decimal("100"))
        assert trade.fees == Decimal("0")

    def test_negative_net_pnl_is_allowed(self):
        """Una posición cerrada con pérdida es un resultado válido, no un error de modelo."""
        trade = _trade(gross_pnl=Decimal("-50"), fees=Decimal("2"), net_pnl=Decimal("-52"))
        assert trade.net_pnl == Decimal("-52")

    def test_dict_round_trip(self):
        trade = _trade()
        assert Trade(**trade.model_dump()) == trade


# --- Position ----------------------------------------------------------------

class TestPosition:
    def test_creates_valid_long_position(self):
        position = _position()
        assert position.side == PositionSide.LONG
        assert position.available_quantity == Decimal("0.1")

    def test_flat_position_requires_zero_quantity(self):
        with pytest.raises(ValidationError):
            _position(side=PositionSide.FLAT, quantity=Decimal("0.1"), average_entry_price=None)

    def test_flat_position_valid_shape(self):
        position = _position(
            side=PositionSide.FLAT, quantity=Decimal("0"), average_entry_price=None,
        )
        assert position.quantity == Decimal("0")
        assert position.average_entry_price is None

    def test_long_position_requires_positive_quantity(self):
        with pytest.raises(ValidationError):
            _position(side=PositionSide.LONG, quantity=Decimal("0"), average_entry_price=Decimal("100"))

    def test_long_position_requires_average_entry_price(self):
        with pytest.raises(ValidationError):
            _position(side=PositionSide.LONG, average_entry_price=None)

    def test_flat_position_rejects_average_entry_price(self):
        with pytest.raises(ValidationError):
            _position(side=PositionSide.FLAT, quantity=Decimal("0"), average_entry_price=Decimal("100"))

    def test_reserved_quantity_cannot_exceed_quantity(self):
        with pytest.raises(ValidationError):
            _position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.2"))

    def test_reserved_quantity_reduces_available_quantity(self):
        position = _position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.04"))
        assert position.available_quantity == Decimal("0.06")

    def test_short_is_reserved_but_constructible(self):
        """SHORT queda reservado en el enum (no prohibido a nivel de modelo) — ver §5.1."""
        position = _position(side=PositionSide.SHORT, quantity=Decimal("0.1"), average_entry_price=Decimal("100"))
        assert position.side == PositionSide.SHORT

    def test_dict_round_trip(self):
        position = _position()
        assert Position(**position.model_dump()) == position


# --- CashBalance -------------------------------------------------------------

class TestCashBalance:
    def test_creates_valid_cash_balance(self):
        cash = _cash_balance()
        assert cash.available_balance == Decimal("10000")

    def test_available_balance_is_computed_not_stored(self):
        cash = _cash_balance(total_balance=Decimal("10000"), reserved_balance=Decimal("5005"))
        assert cash.available_balance == Decimal("4995")
        assert "available_balance" not in cash.model_dump()

    def test_rejects_negative_total_balance(self):
        with pytest.raises(ValidationError):
            _cash_balance(total_balance=Decimal("-1"))

    def test_rejects_negative_reserved_balance(self):
        with pytest.raises(ValidationError):
            _cash_balance(reserved_balance=Decimal("-1"))

    def test_reserved_balance_cannot_exceed_total_balance(self):
        with pytest.raises(ValidationError):
            _cash_balance(total_balance=Decimal("100"), reserved_balance=Decimal("200"))

    def test_dict_round_trip(self):
        cash = _cash_balance(reserved_balance=Decimal("100"))
        assert CashBalance(**cash.model_dump()) == cash


# --- PortfolioSnapshot ---------------------------------------------------

class TestPortfolioSnapshot:
    def test_creates_valid_snapshot(self):
        snapshot = _portfolio_snapshot()
        assert snapshot.total_equity == snapshot.cash_balance + snapshot.positions_value

    def test_rejects_total_equity_mismatch(self):
        with pytest.raises(ValidationError):
            _portfolio_snapshot(
                cash_balance=Decimal("5000"), positions_value=Decimal("5000"),
                total_equity=Decimal("9999"),
            )

    def test_rejects_negative_cash_balance(self):
        with pytest.raises(ValidationError):
            _portfolio_snapshot(cash_balance=Decimal("-1"))

    def test_dict_round_trip(self):
        snapshot = _portfolio_snapshot()
        assert PortfolioSnapshot(**snapshot.model_dump()) == snapshot


# --- PnLSnapshot ----------------------------------------------------------

class TestPnLSnapshot:
    def test_creates_valid_snapshot(self):
        snapshot = _pnl_snapshot()
        assert snapshot.symbol == "BTCUSDT"

    def test_rejects_negative_position_quantity(self):
        with pytest.raises(ValidationError):
            _pnl_snapshot(position_quantity=Decimal("-1"))

    def test_allows_negative_unrealized_pnl(self):
        snapshot = _pnl_snapshot(unrealized_pnl=Decimal("-25"))
        assert snapshot.unrealized_pnl == Decimal("-25")

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            _pnl_snapshot(symbol="")

    def test_dict_round_trip(self):
        snapshot = _pnl_snapshot()
        assert PnLSnapshot(**snapshot.model_dump()) == snapshot


# --- RiskValidationResult -------------------------------------------------

class TestRiskValidationResult:
    def test_creates_valid_approved_result(self):
        result = _risk_result()
        assert result.approved is True
        assert result.metrics_used["available_balance"] == Decimal("4995")

    def test_creates_valid_rejected_result(self):
        result = _risk_result(approved=False, code="INSUFFICIENT_CAPITAL", message="Capital insuficiente.")
        assert result.approved is False
        assert result.code == "INSUFFICIENT_CAPITAL"

    def test_rejects_empty_code(self):
        with pytest.raises(ValidationError):
            _risk_result(code="")

    def test_rejects_empty_rules_version(self):
        with pytest.raises(ValidationError):
            _risk_result(rules_version="")

    def test_metrics_and_limits_default_to_empty_dict(self):
        result = _risk_result(metrics_used={}, limits_used={})
        assert result.metrics_used == {}
        assert result.limits_used == {}

    def test_dict_round_trip(self):
        result = _risk_result()
        assert RiskValidationResult(**result.model_dump()) == result

    def test_json_round_trip_preserves_decimal_in_dicts(self):
        result = _risk_result()
        rebuilt = RiskValidationResult.model_validate_json(result.model_dump_json())
        assert rebuilt == result
        assert isinstance(rebuilt.metrics_used["available_balance"], Decimal)
