"""
Pruebas para InspectionJob (Etapa 6.9): combina Clock/IdGenerator/
InspectionService/AlertDeliveryService, con no-solapamiento. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §23.12.
"""

from datetime import datetime, timezone
from decimal import Decimal

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_sink import NullInspectionAlertSink
from src.paper_trading.inspection_job import InspectionJob
from src.paper_trading.inspection_service import InspectionService
from src.paper_trading.models import CashBalance
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed
        self.call_count = 0

    def now(self) -> datetime:
        self.call_count += 1
        return self._fixed


class DeterministicIdGenerator:
    def __init__(self):
        self._n = 0

    def _next(self, prefix):
        self._n += 1
        return f"{prefix}-{self._n}"

    def new_inspection_run_id(self) -> str:
        return self._next("run")

    def new_inspection_alert_id(self) -> str:
        return self._next("alert")


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
    return repo


def _job(repo, deliver_alerts=True, clock=None, id_generator=None) -> InspectionJob:
    clock = clock or FixedClock(_now())
    id_generator = id_generator or DeterministicIdGenerator()
    inspection_service = InspectionService(
        repository=repo, reconciliation_service=ReconciliationService(repo),
        id_generator=id_generator, clock=clock,
    )
    delivery_service = AlertDeliveryService(repo, NullInspectionAlertSink(clock=clock), max_attempts=3)
    return InspectionJob(
        inspection_service=inspection_service, alert_delivery_service=delivery_service,
        clock=clock, id_generator=id_generator, deliver_alerts=deliver_alerts,
    )


class TestRunOnceSuccessful:
    def test_run_once_succeeds(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo)
        result = job.run_once()
        assert result.success is True
        assert result.skipped is False
        assert result.run_id is not None

    def test_uses_deterministic_clock_and_ids(self, tmp_path):
        repo = _repo(tmp_path)
        clock = FixedClock(_now())
        id_gen = DeterministicIdGenerator()
        job = _job(repo, clock=clock, id_generator=id_gen)
        result = job.run_once()
        assert result.run_id == "run-1"
        assert result.started_at == _now()
        assert result.completed_at == _now()


class TestAlertDelivery:
    def test_delivery_enabled_delivers_alerts(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo, deliver_alerts=True)
        result = job.run_once()
        assert result.delivered_count >= 1

    def test_delivery_disabled_does_not_deliver(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo, deliver_alerts=False)
        result = job.run_once()
        assert result.delivered_count == 0
        assert repo.fetch_pending_inspection_alerts() != []


class TestFailedInspection:
    def test_failed_inspection_is_reported_not_raised(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        clock = FixedClock(_now())
        id_gen = DeterministicIdGenerator()
        reconciliation = ReconciliationService(repo)
        monkeypatch.setattr(reconciliation, "inspect", lambda timestamp: (_ for _ in ()).throw(RuntimeError("boom")))
        inspection_service = InspectionService(
            repository=repo, reconciliation_service=reconciliation, id_generator=id_gen, clock=clock,
        )
        delivery_service = AlertDeliveryService(repo, NullInspectionAlertSink(clock=clock), max_attempts=3)
        job = InspectionJob(inspection_service, delivery_service, clock, id_gen)
        result = job.run_once()
        assert result.success is False
        assert result.error_message == "boom"


class TestNoOverlap:
    def test_second_call_is_skipped_while_lock_held(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo)
        job._lock.acquire()
        try:
            result = job.run_once()
            assert result.skipped is True
            assert result.success is False
        finally:
            job._lock.release()

    def test_lock_is_released_after_normal_run(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo)
        job.run_once()
        acquired = job._lock.acquire(blocking=False)
        assert acquired is True
        job._lock.release()

    def test_lock_is_released_after_exception(self, tmp_path):
        repo = _repo(tmp_path)
        clock = FixedClock(_now())
        id_gen = DeterministicIdGenerator()

        class ExplodingInspectionService:
            def run_inspection(self, run_id, started_at):
                raise RuntimeError("catastrophic")

        delivery_service = AlertDeliveryService(repo, NullInspectionAlertSink(clock=clock), max_attempts=3)
        job = InspectionJob(ExplodingInspectionService(), delivery_service, clock, id_gen)

        try:
            job.run_once()
        except RuntimeError:
            pass

        acquired = job._lock.acquire(blocking=False)
        assert acquired is True
        job._lock.release()

    def test_run_once_after_skip_succeeds(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo)
        job._lock.acquire()
        job.run_once()
        job._lock.release()
        result = job.run_once()
        assert result.skipped is False
        assert result.success is True


class TestDoesNotCallRepairOrTrade:
    def test_run_once_does_not_touch_operational_data(self, tmp_path):
        repo = _repo(tmp_path)
        job = _job(repo)
        job.run_once()
        assert repo.get_cash_balance("USDT").total_balance == Decimal("10000")
        assert repo.fetch_orders(limit=None) == []
        assert repo.fetch_executions(limit=None) == []
        assert repo.fetch_trades(limit=None) == []
