"""
Pruebas para ReconciliationService (Etapa 6.8): orquesta
ReconciliationEngine + PaperTradingRepository, con dry-run por defecto.

Usa SQLitePaperTradingRepository real con tmp_path (no mockea sqlite3).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.exceptions import ReconciliationConflictError, UnsupportedRepairError
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.reconciliation_models import IssueCode
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    return repo


def _pending_buy(**overrides) -> Order:
    now = _now()
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
        created_at=now, updated_at=now, reserved_price=Decimal("50000"),
        reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _pending_sell(**overrides) -> Order:
    now = _now()
    defaults = dict(
        id="order-2", exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=Decimal("0.05"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
        created_at=now, updated_at=now, reserved_price=Decimal("50000"), reserved_quantity=Decimal("0.05"),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(currency="USDT", total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


def _long_position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("40000"), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestInspect:
    def test_no_inconsistencies_on_fresh_account(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        service = ReconciliationService(repo)
        report = service.inspect(_now())
        assert report.is_consistent is True

    def test_multiple_inconsistencies_detected(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        repo.save_position(_long_position(reserved_quantity=Decimal("0.02")))
        service = ReconciliationService(repo)
        report = service.inspect(_now())
        codes = {issue.code for issue in report.issues}
        assert IssueCode.ORPHAN_CASH_RESERVATION in codes
        assert IssueCode.ORPHAN_POSITION_RESERVATION in codes

    def test_inspect_never_writes(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        service.inspect(_now())
        # Sin repair(), el estado persistido no cambia.
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("999")


class TestRepairDryRun:
    def test_dry_run_does_not_write(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        result = service.repair(audit_id="a1", timestamp=_now(), dry_run=True)
        assert result.dry_run is True
        assert result.success is True
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("999")

    def test_dry_run_describes_operations(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        result = service.repair(audit_id="a1", timestamp=_now(), dry_run=True)
        assert len(result.operations_applied) == 1
        op = result.operations_applied[0]
        assert op.old_value == Decimal("999")
        assert op.new_value == Decimal("0")

    def test_dry_run_still_writes_audit_record(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        service.repair(audit_id="audit-dry", timestamp=_now(), dry_run=True)

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            row = conn.execute(
                "SELECT dry_run, success FROM paper_trading_reconciliation_audit WHERE id = ?", ("audit-dry",),
            ).fetchone()
        finally:
            conn.close()
        assert row == (1, 1)


class TestRepairApply:
    def test_apply_fixes_cash_aggregate(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        result = service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        assert result.dry_run is False
        assert result.success is True
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")

    def test_apply_fixes_quantity_aggregate(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        repo.save_position(_long_position(reserved_quantity=Decimal("0.02")))
        service = ReconciliationService(repo)
        result = service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        assert result.success is True
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0")

    def test_apply_fixes_both_in_one_transaction(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        repo.save_position(_long_position(reserved_quantity=Decimal("0.02")))
        service = ReconciliationService(repo)
        result = service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        assert len(result.operations_applied) == 2
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0")

    def test_apply_computes_correct_value_from_pending_orders(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("1")))
        repo.save_order(_pending_buy())
        service = ReconciliationService(repo)
        service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")


class TestFilterByIssueCodes:
    def test_only_requested_code_is_repaired(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        repo.save_position(_long_position(reserved_quantity=Decimal("0.02")))
        service = ReconciliationService(repo)
        result = service.repair(
            audit_id="a1", timestamp=_now(), dry_run=False,
            issue_codes=[IssueCode.ORPHAN_CASH_RESERVATION],
        )
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0.02")
        assert IssueCode.ORPHAN_POSITION_RESERVATION in result.skipped_issue_codes

    def test_unsupported_issue_code_raises(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        service = ReconciliationService(repo)
        with pytest.raises(UnsupportedRepairError):
            service.repair(
                audit_id="a1", timestamp=_now(), dry_run=False,
                issue_codes=[IssueCode.FILLED_ORDER_WITHOUT_EXECUTION],
            )


class TestNoOpRepair:
    def test_repair_with_nothing_to_fix_succeeds_without_operations(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        service = ReconciliationService(repo)
        result = service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        assert result.success is True
        assert result.operations_applied == ()
        assert result.repaired_issue_codes == ()


class TestIdempotency:
    def test_inspect_twice_produces_same_logical_report(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        report1 = service.inspect(_now())
        report2 = service.inspect(_now())
        assert [i.code for i in report1.issues] == [i.code for i in report2.issues]

    def test_repairing_twice_does_not_reapply(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)
        result1 = service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        result2 = service.repair(audit_id="a2", timestamp=_now(), dry_run=False)
        assert len(result1.operations_applied) == 1
        assert result2.operations_applied == ()
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")

    def test_no_double_release_of_reservation(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        repo.save_order(_pending_buy())
        service = ReconciliationService(repo)
        service.repair(audit_id="a1", timestamp=_now(), dry_run=False)
        service.repair(audit_id="a2", timestamp=_now(), dry_run=False)
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")


class TestConcurrencyConflict:
    def test_conflict_raised_if_value_changed_between_inspect_and_apply(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)

        original_get_cash_balance = repo.get_cash_balance

        def _drifted_get_cash_balance(currency="USDT"):
            balance = original_get_cash_balance(currency)
            return CashBalance(**{**balance.model_dump(), "reserved_balance": Decimal("500")})

        monkeypatch.setattr(repo, "get_cash_balance", _drifted_get_cash_balance)

        with pytest.raises(ReconciliationConflictError):
            service.repair(audit_id="a1", timestamp=_now(), dry_run=False)

        # Nada se escribió: reserved_balance sigue siendo el original (999), no 500 ni 0.
        monkeypatch.undo()
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("999")


class TestStructuralFailurePropagates:
    def test_repository_failure_during_apply_is_reraised_and_audited(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        service = ReconciliationService(repo)

        def _boom(cash_balances, positions, audit_record):
            raise RuntimeError("simulated write failure")

        monkeypatch.setattr(repo, "save_reconciliation_transaction", _boom)

        with pytest.raises(RuntimeError):
            service.repair(audit_id="audit-fail", timestamp=_now(), dry_run=False)

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            row = conn.execute(
                "SELECT success, error_message FROM paper_trading_reconciliation_audit WHERE id = ?",
                ("audit-fail",),
            ).fetchone()
        finally:
            conn.close()
        assert row == (0, "simulated write failure")


class TestNeverTouchesOrdersExecutionsTrades:
    def test_repair_does_not_create_execution_or_trade_or_change_order_status(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("999")))
        order = _pending_buy()
        repo.save_order(order)
        service = ReconciliationService(repo)
        service.repair(audit_id="a1", timestamp=_now(), dry_run=False)

        fetched_order = repo.get_order("order-1")
        assert fetched_order.status == OrderStatus.PENDING
        assert repo.fetch_executions_by_order("order-1") == []
        assert repo.fetch_trades() == []


class TestEndToEndReconciliation:
    """Paso 36: prueba integral de punta a punta."""

    def test_full_cycle_detect_dry_run_apply_idempotent(self, tmp_path):
        repo = _repo(tmp_path)
        now = _now()

        # 1-3. Sembrar CashBalance + BUY PENDING + SELL PENDING válidas.
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("5005")))
        repo.save_position(_long_position(reserved_quantity=Decimal("0.05")))
        repo.save_order(_pending_buy())
        repo.save_order(_pending_sell())

        service = ReconciliationService(repo)
        report_before = service.inspect(now)
        assert report_before.is_consistent is True

        # 5. Corromper de manera controlada los agregados de reserva.
        corrupted_cash = CashBalance(**{**repo.get_cash_balance("USDT").model_dump(), "reserved_balance": Decimal("999")})
        repo.save_cash_balance(corrupted_cash)
        corrupted_position = Position(**{
            **repo.get_position("Binance", "BTCUSDT").model_dump(), "reserved_quantity": Decimal("0.09"),
        })
        repo.save_position(corrupted_position)

        orders_before = repo.fetch_orders(limit=None)
        executions_before = repo.fetch_executions(limit=None)
        trades_before = repo.fetch_trades(limit=None)

        # 6-7. inspect() detecta las inconsistencias.
        report_corrupt = service.inspect(now)
        codes = {issue.code for issue in report_corrupt.issues}
        assert IssueCode.CASH_RESERVED_BALANCE_MISMATCH in codes
        assert IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH in codes

        # 8-9. dry-run no cambia nada.
        dry_result = service.repair(audit_id="audit-dry", timestamp=now, dry_run=True)
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("999")
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0.09")

        # 10-11. apply corrige.
        apply_result = service.repair(audit_id="audit-apply", timestamp=now, dry_run=False)
        assert apply_result.success is True
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0.05")

        # 12-13. Nueva inspección confirma consistencia.
        report_after = service.inspect(now)
        assert report_after.is_consistent is True

        # 14-15. Repetir apply es idempotente.
        second_apply = service.repair(audit_id="audit-apply-2", timestamp=now, dry_run=False)
        assert second_apply.operations_applied == ()

        # 16. Orders/Executions/Trades idénticos antes/después.
        assert repo.fetch_orders(limit=None) == orders_before
        assert repo.fetch_executions(limit=None) == executions_before
        assert repo.fetch_trades(limit=None) == trades_before

        # 17. Auditoría de las 3 corridas de reparación queda registrada.
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            count = conn.execute("SELECT COUNT(*) FROM paper_trading_reconciliation_audit").fetchone()[0]
        finally:
            conn.close()
        assert count == 3  # audit-dry, audit-apply, audit-apply-2
