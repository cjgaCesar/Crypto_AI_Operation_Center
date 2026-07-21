"""
Pruebas para ReconciliationEngine (Etapa 6.8): detección pura de
inconsistencias de estado. Ver docs/ARQUITECTURA_PAPER_TRADING.md §22.
"""

from datetime import datetime, timezone
from decimal import Decimal

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide
from src.paper_trading.models import CashBalance, Execution, Order, Position, Trade
from src.paper_trading.reconciliation_engine import ReconciliationEngine
from src.paper_trading.reconciliation_models import IssueCode, IssueSeverity


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(side: OrderSide = OrderSide.BUY, status: OrderStatus = OrderStatus.PENDING, **overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=side, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=status, source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _pending_buy(**overrides) -> Order:
    defaults = dict(
        reserved_price=Decimal("50000"), reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
    )
    defaults.update(overrides)
    return _order(side=OrderSide.BUY, status=OrderStatus.PENDING, **defaults)


def _pending_sell(**overrides) -> Order:
    defaults = dict(reserved_price=Decimal("50000"), reserved_quantity=Decimal("0.1"))
    defaults.update(overrides)
    return _order(side=OrderSide.SELL, status=OrderStatus.PENDING, **defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(currency="USDT", total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


def _long_position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


def _execution(**overrides) -> Execution:
    defaults = dict(
        id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
        quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=_now(),
    )
    defaults.update(overrides)
    return Execution(**defaults)


def _trade(**overrides) -> Trade:
    now = _now()
    defaults = dict(
        id="trade-1", exchange="Binance", symbol="BTCUSDT", side=TradeSide.LONG, quantity=Decimal("0.1"),
        entry_price=Decimal("40000"), exit_price=Decimal("50000"), gross_pnl=Decimal("1000"),
        fees=Decimal("5"), net_pnl=Decimal("995"), opened_at=now, closed_at=now, exit_execution_id="exec-1",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def _analyze(orders=(), executions=(), trades=(), positions=(), cash_balances=(), timestamp=None):
    return ReconciliationEngine.analyze(
        list(orders), list(executions), list(trades), list(positions), list(cash_balances),
        timestamp or _now(),
    )


class TestEmptyState:
    def test_no_activity_produces_single_info_issue(self):
        report = _analyze(cash_balances=[_cash_balance()])
        assert [i.code for i in report.issues] == [IssueCode.NO_ACTIVITY]
        assert report.issues[0].severity == IssueSeverity.INFO
        assert report.is_consistent is True

    def test_report_counts_are_all_zero_besides_info(self):
        report = _analyze(cash_balances=[_cash_balance()])
        assert report.critical_count == 0
        assert report.error_count == 0
        assert report.warning_count == 0
        assert report.info_count == 1
        assert report.repairable_count == 0
        assert report.total_issues == 1


class TestPendingBuyValid:
    def test_valid_pending_buy_produces_no_issue(self):
        order = _pending_buy()
        cash = _cash_balance(reserved_balance=Decimal("5005"))
        report = _analyze(orders=[order], cash_balances=[cash])
        assert report.issues == ()
        assert report.is_consistent is True

    def test_missing_reservation_is_error(self):
        order = _order(side=OrderSide.BUY, status=OrderStatus.PENDING)
        report = _analyze(orders=[order], cash_balances=[_cash_balance()])
        codes = [i.code for i in report.issues]
        assert IssueCode.PENDING_BUY_MISSING_RESERVATION in codes
        issue = next(i for i in report.issues if i.code == IssueCode.PENDING_BUY_MISSING_RESERVATION)
        assert issue.severity == IssueSeverity.ERROR
        assert issue.repairable is False

    def test_partial_reservation_is_critical(self):
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
        )
        report = _analyze(orders=[order], cash_balances=[_cash_balance()])
        codes = [i.code for i in report.issues]
        assert IssueCode.PENDING_ORDER_INVALID_RESERVED_PRICE in codes
        issue = next(i for i in report.issues if i.code == IssueCode.PENDING_ORDER_INVALID_RESERVED_PRICE)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_reserved_cash_mismatch_is_critical(self):
        order = _pending_buy(reserved_notional=Decimal("9999"))
        cash = _cash_balance(total_balance=Decimal("20000"), reserved_balance=Decimal("10004"))
        report = _analyze(orders=[order], cash_balances=[cash])
        issue = next(i for i in report.issues if i.code == IssueCode.PENDING_BUY_RESERVED_CASH_MISMATCH)
        assert issue.severity == IssueSeverity.CRITICAL
        assert issue.expected_value == Decimal("5000")
        assert issue.actual_value == Decimal("9999")

    def test_reserved_quantity_on_buy_is_defensive_side_mismatch(self):
        order = _pending_buy().model_copy(update={"reserved_quantity": None})
        broken = Order.model_construct(**{**order.model_dump(), "reserved_quantity": Decimal("0.1")})
        report = _analyze(orders=[broken], cash_balances=[_cash_balance(reserved_balance=Decimal("5005"))])
        codes = [i.code for i in report.issues]
        assert IssueCode.ORDER_RESERVATION_SIDE_MISMATCH in codes


class TestPendingSellValid:
    def test_valid_pending_sell_produces_no_issue(self):
        order = _pending_sell()
        position = _long_position(reserved_quantity=Decimal("0.1"))
        report = _analyze(orders=[order], positions=[position], cash_balances=[_cash_balance()])
        assert report.issues == ()

    def test_missing_reservation_is_error(self):
        order = _order(side=OrderSide.SELL, status=OrderStatus.PENDING)
        position = _long_position()
        report = _analyze(orders=[order], positions=[position], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.PENDING_SELL_MISSING_RESERVATION)
        assert issue.severity == IssueSeverity.ERROR

    def test_reserved_quantity_mismatch_is_critical(self):
        order = _pending_sell(reserved_quantity=Decimal("0.05"))
        position = _long_position(reserved_quantity=Decimal("0.05"))
        report = _analyze(orders=[order], positions=[position], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.PENDING_SELL_RESERVED_QUANTITY_MISMATCH)
        assert issue.severity == IssueSeverity.CRITICAL
        assert issue.expected_value == Decimal("0.1")
        assert issue.actual_value == Decimal("0.05")

    def test_missing_long_position_is_reported(self):
        order = _pending_sell()
        report = _analyze(orders=[order], positions=[], cash_balances=[_cash_balance()])
        codes = [i.code for i in report.issues]
        assert IssueCode.PENDING_SELL_RESERVED_QUANTITY_MISMATCH in codes


class TestCashAggregate:
    def test_orphan_cash_reservation(self):
        cash = _cash_balance(reserved_balance=Decimal("100"))
        report = _analyze(cash_balances=[cash])
        issue = next(i for i in report.issues if i.code == IssueCode.ORPHAN_CASH_RESERVATION)
        assert issue.severity == IssueSeverity.ERROR
        assert issue.repairable is True
        assert issue.expected_value == Decimal("0")
        assert issue.actual_value == Decimal("100")

    def test_cash_reserved_balance_mismatch(self):
        order = _pending_buy()
        cash = _cash_balance(reserved_balance=Decimal("1"))
        report = _analyze(orders=[order], cash_balances=[cash])
        issue = next(i for i in report.issues if i.code == IssueCode.CASH_RESERVED_BALANCE_MISMATCH)
        assert issue.severity == IssueSeverity.ERROR
        assert issue.repairable is True
        assert issue.expected_value == Decimal("5005")

    def test_multiple_pending_buy_orders_sum_exactly(self):
        order1 = _pending_buy(id="o1")
        order2 = _pending_buy(
            id="o2", quantity=Decimal("0.06"), reserved_notional=Decimal("3000"), reserved_fee=Decimal("3"),
        )
        cash = _cash_balance(reserved_balance=Decimal("8008"))
        report = _analyze(orders=[order1, order2], cash_balances=[cash])
        assert report.issues == ()


class TestQuantityAggregate:
    def test_orphan_position_reservation(self):
        position = _long_position(reserved_quantity=Decimal("0.05"))
        report = _analyze(positions=[position], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.ORPHAN_POSITION_RESERVATION)
        assert issue.severity == IssueSeverity.ERROR
        assert issue.repairable is True

    def test_position_reserved_quantity_mismatch(self):
        order = _pending_sell()
        position = _long_position(reserved_quantity=Decimal("0.03"))
        report = _analyze(orders=[order], positions=[position], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH)
        assert issue.severity == IssueSeverity.ERROR
        assert issue.expected_value == Decimal("0.1")
        assert issue.actual_value == Decimal("0.03")


class TestTerminalOrders:
    def test_rejected_order_with_reservation_is_error(self):
        base = _order(side=OrderSide.BUY, status=OrderStatus.NEW)
        rejected = Order.model_construct(**{
            **base.model_dump(), "status": OrderStatus.REJECTED, "rejection_reason": "riesgo",
            "reserved_price": Decimal("50000"), "reserved_notional": Decimal("5000"), "reserved_fee": Decimal("5"),
        })
        report = _analyze(orders=[rejected], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.TERMINAL_ORDER_HAS_RESERVATION)
        assert issue.severity == IssueSeverity.ERROR
        assert issue.repairable is False

    def test_rejected_order_without_reservation_is_clean(self):
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.REJECTED, rejection_reason="riesgo",
        )
        report = _analyze(orders=[order], cash_balances=[_cash_balance()])
        assert report.issues == ()

    def test_filled_order_with_historical_reservation_fields_is_not_flagged(self):
        """FILLED conserva sus campos de reserva históricos por diseño (§21.2) -- no es un issue."""
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"), reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        report = _analyze(orders=[order], executions=[execution], cash_balances=[_cash_balance()])
        assert report.issues == ()


class TestFilledOrders:
    def test_filled_without_execution_is_critical(self):
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        report = _analyze(orders=[order], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.FILLED_ORDER_WITHOUT_EXECUTION)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_multiple_executions_is_warning(self):
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        exec1 = _execution(id="e1", quantity=Decimal("0.05"))
        exec2 = _execution(id="e2", quantity=Decimal("0.05"))
        report = _analyze(orders=[order], executions=[exec1, exec2], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER)
        assert issue.severity == IssueSeverity.WARNING
        assert issue.repairable is False

    def test_execution_mismatch_is_critical(self):
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        execution = _execution(quantity=Decimal("0.2"), price=Decimal("50000"))
        report = _analyze(orders=[order], executions=[execution], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.FILLED_ORDER_EXECUTION_MISMATCH)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_valid_filled_order_produces_no_issue(self):
        order = _order(
            side=OrderSide.BUY, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        report = _analyze(orders=[order], executions=[execution], cash_balances=[_cash_balance()])
        assert report.issues == ()


class TestExecutions:
    def test_orphan_execution_missing_order(self):
        execution = _execution(order_id="does-not-exist")
        report = _analyze(executions=[execution], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.ORPHAN_EXECUTION)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_orphan_execution_symbol_mismatch(self):
        order = _order(side=OrderSide.BUY, status=OrderStatus.FILLED, symbol="BTCUSDT")
        execution = _execution(symbol="ETHUSDT")
        report = _analyze(orders=[order], executions=[execution], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.ORPHAN_EXECUTION)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_execution_for_non_filled_order(self):
        order = _pending_buy()
        execution = _execution()
        report = _analyze(
            orders=[order], executions=[execution],
            cash_balances=[_cash_balance(reserved_balance=Decimal("5005"))],
        )
        issue = next(i for i in report.issues if i.code == IssueCode.EXECUTION_FOR_NON_FILLED_ORDER)
        assert issue.severity == IssueSeverity.CRITICAL


class TestTrades:
    def test_trade_without_exit_execution(self):
        trade = _trade(exit_execution_id="does-not-exist")
        report = _analyze(trades=[trade], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.TRADE_WITHOUT_EXIT_EXECUTION)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_trade_execution_belongs_to_buy_order(self):
        order = _order(side=OrderSide.BUY, status=OrderStatus.FILLED)
        execution = _execution()
        trade = _trade()
        report = _analyze(orders=[order], executions=[execution], trades=[trade], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.TRADE_WITHOUT_EXIT_EXECUTION)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_sell_filled_without_trade(self):
        order = _order(
            side=OrderSide.SELL, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        report = _analyze(orders=[order], executions=[execution], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.SELL_FILLED_WITHOUT_TRADE)
        assert issue.severity == IssueSeverity.CRITICAL

    def test_valid_sell_filled_with_trade_produces_no_issue(self):
        order = _order(
            side=OrderSide.SELL, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        trade = _trade()
        position = _long_position(quantity=Decimal("0"), side=PositionSide.FLAT, average_entry_price=None)
        position = Position.model_construct(**{**position.model_dump(), "realized_pnl_to_date": Decimal("995")})
        report = _analyze(
            orders=[order], executions=[execution], trades=[trade], positions=[position],
            cash_balances=[_cash_balance()],
        )
        assert report.issues == ()


class TestPnlConsistency:
    def test_inconsistent_pnl_is_warning(self):
        position = _long_position(realized_pnl_to_date=Decimal("100"))
        trade = _trade(net_pnl=Decimal("995"))
        report = _analyze(positions=[position], trades=[trade], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.POSITION_PNL_INCONSISTENT)
        assert issue.severity == IssueSeverity.WARNING
        assert issue.repairable is False
        assert issue.expected_value == Decimal("995")
        assert issue.actual_value == Decimal("100")

    def test_consistent_pnl_produces_no_issue(self):
        order = _order(
            side=OrderSide.SELL, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
        )
        execution = _execution(quantity=Decimal("0.1"), price=Decimal("50000"))
        position = _long_position(
            quantity=Decimal("0"), side=PositionSide.FLAT, average_entry_price=None,
        )
        position = Position.model_construct(**{**position.model_dump(), "realized_pnl_to_date": Decimal("995")})
        trade = _trade(net_pnl=Decimal("995"))
        report = _analyze(
            orders=[order], executions=[execution], trades=[trade], positions=[position],
            cash_balances=[_cash_balance()],
        )
        assert report.issues == ()


class TestNegativeValuesDefensive:
    def test_negative_available_cash(self):
        base = _cash_balance(total_balance=Decimal("100"), reserved_balance=Decimal("50"))
        broken = CashBalance.model_construct(**{**base.model_dump(), "reserved_balance": Decimal("150")})
        report = _analyze(cash_balances=[broken])
        issue = next(i for i in report.issues if i.code == IssueCode.NEGATIVE_AVAILABLE_CASH)
        assert issue.severity == IssueSeverity.CRITICAL
        assert issue.repairable is False

    def test_negative_available_quantity(self):
        base = _long_position(quantity=Decimal("0.1"), reserved_quantity=Decimal("0.05"))
        broken = Position.model_construct(**{**base.model_dump(), "reserved_quantity": Decimal("0.2")})
        report = _analyze(positions=[broken], cash_balances=[_cash_balance()])
        issue = next(i for i in report.issues if i.code == IssueCode.NEGATIVE_AVAILABLE_QUANTITY)
        assert issue.severity == IssueSeverity.CRITICAL


class TestDeterminismAndPurity:
    def test_issues_are_sorted_deterministically(self):
        order1 = _order(id="z-order", side=OrderSide.BUY, status=OrderStatus.PENDING)
        order2 = _order(id="a-order", side=OrderSide.BUY, status=OrderStatus.PENDING)
        report1 = _analyze(orders=[order1, order2], cash_balances=[_cash_balance()])
        report2 = _analyze(orders=[order2, order1], cash_balances=[_cash_balance()])
        assert [(i.code, i.entity_id) for i in report1.issues] == [(i.code, i.entity_id) for i in report2.issues]

    def test_analyze_does_not_mutate_inputs(self):
        order = _pending_buy()
        cash = _cash_balance(reserved_balance=Decimal("1"))
        order_copy = order.model_copy(deep=True)
        cash_copy = cash.model_copy(deep=True)
        ReconciliationEngine.analyze([order], [], [], [], [cash], _now())
        assert order == order_copy
        assert cash == cash_copy

    def test_analyze_is_repeatable_without_side_effects(self):
        order = _pending_buy()
        cash = _cash_balance(reserved_balance=Decimal("1"))
        report1 = _analyze(orders=[order], cash_balances=[cash])
        report2 = _analyze(orders=[order], cash_balances=[cash])
        assert [i.code for i in report1.issues] == [i.code for i in report2.issues]

    def test_decimal_exactness_no_float_involved(self):
        order = _pending_buy(reserved_notional=Decimal("5000.123456789"))
        cash = _cash_balance(reserved_balance=Decimal("5005.123456789"))
        report = _analyze(orders=[order], cash_balances=[cash])
        mismatch = next((i for i in report.issues if i.code == IssueCode.PENDING_BUY_RESERVED_CASH_MISMATCH), None)
        assert mismatch is not None
        assert mismatch.expected_value == Decimal("5000")
