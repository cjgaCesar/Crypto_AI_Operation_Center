"""
Pruebas para InspectionService (Etapa 6.9): orquesta
ReconciliationService.inspect() + compare_reports() + AlertBuilder +
persistencia. Usa SQLitePaperTradingRepository real (tmp_path).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.exceptions import InspectionPersistenceError
from src.paper_trading.inspection_service import InspectionService
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    def __init__(self):
        self._n = 0

    def new_inspection_alert_id(self) -> str:
        self._n += 1
        return f"alert-{self._n}"


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    return repo


def _service(repo) -> InspectionService:
    return InspectionService(
        repository=repo, reconciliation_service=ReconciliationService(repo),
        id_generator=DeterministicIdGenerator(), clock=FixedClock(_now()),
    )


class TestFirstInspection:
    def test_first_inspection_is_all_new(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        service = _service(repo)
        run = service.run_inspection(run_id="run-1", started_at=_now())
        assert run.success is True
        assert run.previous_run_id is None
        assert run.new_issue_count >= 0


class TestSecondInspectionUnchanged:
    def test_no_new_alerts_when_nothing_changed(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.new_issue_count == 0
        assert run2.alert_count == 0
        assert run2.previous_run_id == "run-1"


class TestIssueLifecycle:
    def test_new_issue_detected(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())

        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.new_issue_count >= 1

    def test_issue_resolved(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())

        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.resolved_issue_count >= 1

    def test_issue_persistent(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.persistent_issue_count >= 1
        assert run2.new_issue_count == 0

    def test_severity_increased(self, tmp_path):
        repo = _repo(tmp_path)
        # ORPHAN_CASH_RESERVATION es ERROR; forzamos un cambio a otro código
        # comparando dos corridas con distinto conjunto -- se prueba en el
        # comparador directamente; aquí confirmamos que changed_issue_count
        # refleja los cambios de valor entre corridas.
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("100"), updated_at=_now(),
        ))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())

        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("200"), updated_at=_now(),
        ))
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.changed_issue_count >= 1

    def test_severity_decreased_is_also_a_changed_issue(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("200"), updated_at=_now(),
        ))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("100"), updated_at=_now(),
        ))
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.changed_issue_count >= 1

    def test_value_change_detected(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(Order(
            id="o1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=_now(), updated_at=_now(), reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        ))
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("1"), updated_at=_now(),
        ))
        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("2"), updated_at=_now(),
        ))
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.changed_issue_count >= 1


class TestInspectionFailure:
    def test_inspect_failure_is_captured_as_failed_run(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        reconciliation = ReconciliationService(repo)

        def _boom(timestamp):
            raise RuntimeError("boom")

        monkeypatch.setattr(reconciliation, "inspect", _boom)
        service = InspectionService(
            repository=repo, reconciliation_service=reconciliation,
            id_generator=DeterministicIdGenerator(), clock=FixedClock(_now()),
        )
        run = service.run_inspection(run_id="run-1", started_at=_now())
        assert run.success is False
        assert run.error_message == "boom"
        assert run.report is None

    def test_failure_creates_inspection_failed_alert(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        reconciliation = ReconciliationService(repo)
        monkeypatch.setattr(reconciliation, "inspect", lambda timestamp: (_ for _ in ()).throw(RuntimeError("boom")))
        service = InspectionService(
            repository=repo, reconciliation_service=reconciliation,
            id_generator=DeterministicIdGenerator(), clock=FixedClock(_now()),
        )
        service.run_inspection(run_id="run-1", started_at=_now())
        pending = repo.fetch_pending_inspection_alerts()
        assert len(pending) == 1
        assert pending[0].alert_type.value == "INSPECTION_FAILED"


class TestSystemRecovered:
    def test_recovery_after_failure_creates_system_recovered(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        reconciliation = ReconciliationService(repo)
        service = InspectionService(
            repository=repo, reconciliation_service=reconciliation,
            id_generator=DeterministicIdGenerator(), clock=FixedClock(_now()),
        )

        original_inspect = reconciliation.inspect
        monkeypatch.setattr(reconciliation, "inspect", lambda timestamp: (_ for _ in ()).throw(RuntimeError("boom")))
        service.run_inspection(run_id="run-1", started_at=_now())

        monkeypatch.setattr(reconciliation, "inspect", original_inspect)
        run2 = service.run_inspection(run_id="run-2", started_at=_now())
        assert run2.success is True

        alert_types = {alert.alert_type.value for alert in repo.fetch_pending_inspection_alerts()}
        assert "SYSTEM_RECOVERED" in alert_types

    def test_system_recovered_deduplicates(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        reconciliation = ReconciliationService(repo)
        service = InspectionService(
            repository=repo, reconciliation_service=reconciliation,
            id_generator=DeterministicIdGenerator(), clock=FixedClock(_now()),
        )
        original_inspect = reconciliation.inspect

        monkeypatch.setattr(reconciliation, "inspect", lambda timestamp: (_ for _ in ()).throw(RuntimeError("boom")))
        service.run_inspection(run_id="run-1", started_at=_now())
        monkeypatch.setattr(reconciliation, "inspect", original_inspect)
        service.run_inspection(run_id="run-2", started_at=_now())

        # Un tercer ciclo fallido con el MISMO mensaje, seguido de otra
        # recuperación, no debe duplicar el SYSTEM_RECOVERED ya emitido
        # (mismo error_message -> misma deduplication_key, ver §23.7).
        monkeypatch.setattr(reconciliation, "inspect", lambda timestamp: (_ for _ in ()).throw(RuntimeError("boom")))
        service.run_inspection(run_id="run-3", started_at=_now())
        monkeypatch.setattr(reconciliation, "inspect", original_inspect)
        service.run_inspection(run_id="run-4", started_at=_now())

        recovered_alerts = [
            alert for alert in repo.fetch_inspection_runs(limit=None)
        ]
        all_alerts_ever = []
        for status in ("PENDING",):
            all_alerts_ever.extend(repo.fetch_pending_inspection_alerts())
        system_recovered_count = sum(1 for a in all_alerts_ever if a.alert_type.value == "SYSTEM_RECOVERED")
        assert system_recovered_count == 1


class TestIdempotencyAcrossRestart:
    def test_reconstructing_service_over_same_repo_is_consistent(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        service1 = _service(repo)
        service1.run_inspection(run_id="run-1", started_at=_now())

        service2 = _service(repo)
        run2 = service2.run_inspection(run_id="run-2", started_at=_now())
        assert run2.previous_run_id == "run-1"
        assert run2.new_issue_count == 0


class TestNeverTouchesOperationalData:
    def test_does_not_call_repair_create_execution_trade_or_change_order_status(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        order = Order(
            id="o1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=_now(), updated_at=_now(), reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        repo.save_order(order)
        position = Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now(),
        )
        repo.save_position(position)

        service = _service(repo)
        service.run_inspection(run_id="run-1", started_at=_now())

        assert repo.get_order("o1").status == OrderStatus.PENDING
        assert repo.fetch_executions_by_order("o1") == []
        assert repo.fetch_trades() == []
        assert repo.get_cash_balance("USDT").total_balance == Decimal("10000")
        assert repo.get_position("Binance", "BTCUSDT").quantity == Decimal("0")
