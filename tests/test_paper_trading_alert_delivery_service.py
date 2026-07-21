"""
Pruebas para AlertDeliveryService (Etapa 6.9, ampliado en 6.10 para
depender de InspectionNotificationChannel): entrega de alertas PENDING
con reintentos acotados. Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9/§24.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus, AlertType, InspectionAlert
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.models import CashBalance, Order
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    return repo


def _seed_alert(repo, alert_id="alert-1", dedup_key="key-1", run_id="run-1") -> InspectionAlert:
    now = _now()
    run = ScheduledInspectionRun(
        id=run_id, started_at=now, completed_at=now, success=True, report=None, previous_run_id=None,
        new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0, changed_issue_count=0, alert_count=1,
    )
    alert = InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=AlertType.NEW_ISSUE, issue_identity=None, issue_code=None,
        severity=None, title="t", message="m", deduplication_key=dedup_key, status=AlertStatus.PENDING,
        delivery_attempts=0, last_error=None, created_at=now,
    )
    repo.save_inspection_run_transaction(run, [alert])
    return alert


class SucceedingSink:
    def __init__(self):
        self.delivered_alerts = []

    def deliver(self, alert):
        self.delivered_alerts.append(alert.id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class FailingSink:
    def deliver(self, alert):
        return AlertDeliveryResult(success=False, error_message="sink failure", delivered_at=_now())


class RaisingSink:
    def deliver(self, alert):
        raise RuntimeError("sink exploded")


class TestSuccessfulDelivery:
    def test_delivers_pending_alert(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)
        sink = SucceedingSink()
        service = AlertDeliveryService(repo, sink, max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 1
        assert result.failed_count == 0
        assert repo.get_inspection_alert_by_deduplication_key("key-1").status == AlertStatus.DELIVERED
        assert sink.delivered_alerts == ["alert-1"]


class TestFailedDelivery:
    def test_sink_failure_keeps_pending_until_max_attempts(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)
        service = AlertDeliveryService(repo, FailingSink(), max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.failed_count == 1
        alert = repo.get_inspection_alert_by_deduplication_key("key-1")
        assert alert.status == AlertStatus.PENDING
        assert alert.delivery_attempts == 1

    def test_reaches_max_attempts_and_becomes_failed(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)
        service = AlertDeliveryService(repo, FailingSink(), max_attempts=2)
        service.deliver_pending_alerts()
        service.deliver_pending_alerts()
        alert = repo.get_inspection_alert_by_deduplication_key("key-1")
        assert alert.status == AlertStatus.FAILED
        assert alert.delivery_attempts == 2
        assert alert.last_error == "sink failure"

    def test_failed_alert_is_never_reattempted(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)
        service = AlertDeliveryService(repo, FailingSink(), max_attempts=1)
        service.deliver_pending_alerts()
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 0
        assert result.failed_count == 0  # ya no está PENDING, no se procesa de nuevo


class TestDeliveredNeverReattempted:
    def test_delivered_alert_is_not_fetched_again(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)
        service = AlertDeliveryService(repo, SucceedingSink(), max_attempts=3)
        service.deliver_pending_alerts()
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 0
        assert result.failed_count == 0


class TestSuppressedNeverDelivered:
    def test_suppressed_alert_is_never_fetched(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _seed_alert(repo)
        repo.update_inspection_alert_delivery(
            alert_id=alert.id, status=AlertStatus.SUPPRESSED, delivery_attempts=0, last_error=None,
            delivered_at=None,
        )
        service = AlertDeliveryService(repo, SucceedingSink(), max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 0
        assert result.failed_count == 0


class TestMultipleAlertsAndBatchLimit:
    def test_processes_several_alerts(self, tmp_path):
        repo = _repo(tmp_path)
        run = ScheduledInspectionRun(
            id="run-1", started_at=_now(), completed_at=_now(), success=True, report=None, previous_run_id=None,
            new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0, changed_issue_count=0,
            alert_count=3,
        )
        alerts = [
            InspectionAlert(
                id=f"alert-{i}", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
                issue_code=None, severity=None, title="t", message="m", deduplication_key=f"key-{i}",
                status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
            )
            for i in range(3)
        ]
        repo.save_inspection_run_transaction(run, alerts)
        sink = SucceedingSink()
        service = AlertDeliveryService(repo, sink, max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 3
        assert sorted(sink.delivered_alerts) == ["alert-0", "alert-1", "alert-2"]

    def test_one_failure_does_not_stop_the_rest(self, tmp_path):
        repo = _repo(tmp_path)
        run = ScheduledInspectionRun(
            id="run-1", started_at=_now(), completed_at=_now(), success=True, report=None, previous_run_id=None,
            new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0, changed_issue_count=0,
            alert_count=2,
        )
        alerts = [
            InspectionAlert(
                id=f"alert-{i}", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
                issue_code=None, severity=None, title="t", message="m", deduplication_key=f"key-{i}",
                status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
            )
            for i in range(2)
        ]
        repo.save_inspection_run_transaction(run, alerts)

        class MixedSink:
            def deliver(self, alert):
                if alert.id == "alert-0":
                    raise RuntimeError("boom")
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        service = AlertDeliveryService(repo, MixedSink(), max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 1
        assert repo.get_inspection_alert_by_deduplication_key("key-1").status == AlertStatus.DELIVERED

    def test_batch_limit_respected(self, tmp_path):
        repo = _repo(tmp_path)
        run = ScheduledInspectionRun(
            id="run-1", started_at=_now(), completed_at=_now(), success=True, report=None, previous_run_id=None,
            new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0, changed_issue_count=0,
            alert_count=3,
        )
        alerts = [
            InspectionAlert(
                id=f"alert-{i}", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
                issue_code=None, severity=None, title="t", message="m", deduplication_key=f"key-{i}",
                status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
            )
            for i in range(3)
        ]
        repo.save_inspection_run_transaction(run, alerts)
        sink = SucceedingSink()
        service = AlertDeliveryService(repo, sink, max_attempts=3)
        result = service.deliver_pending_alerts(limit=1)
        assert result.delivered_count == 1


class TestNoOperationalMutations:
    def test_does_not_modify_orders_or_balances(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(currency="USDT", total_balance=Decimal("10000"), updated_at=_now()))
        order = Order(
            id="o1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=_now(), updated_at=_now(),
        )
        repo.save_order(order)
        _seed_alert(repo)
        service = AlertDeliveryService(repo, SucceedingSink(), max_attempts=3)
        service.deliver_pending_alerts()
        assert repo.get_order("o1").status == OrderStatus.PENDING
        assert repo.get_cash_balance("USDT").total_balance == Decimal("10000")


class TestConstructorValidation:
    def test_max_attempts_must_be_positive(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(ValueError):
            AlertDeliveryService(repo, SucceedingSink(), max_attempts=0)


class TestWorksWithCompositeNotificationChannel:
    """Etapa 6.10: AlertDeliveryService debe funcionar exactamente igual
    cuando el canal inyectado es un CompositeNotificationChannel -- sin
    ningún cambio de comportamiento respecto de un sink individual."""

    def test_delivers_via_composite_with_one_channel(self, tmp_path):
        from src.paper_trading.notification_channels import CompositeNotificationChannel, NullNotificationChannel

        repo = _repo(tmp_path)
        _seed_alert(repo)
        composite = CompositeNotificationChannel([NullNotificationChannel()], repository=repo, max_attempts=3)
        service = AlertDeliveryService(repo, composite, max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 1
        assert repo.get_inspection_alert_by_deduplication_key("key-1").status == AlertStatus.DELIVERED

    def test_delivers_via_composite_with_multiple_channels(self, tmp_path):
        from src.paper_trading.notification_channels import (
            CompositeNotificationChannel, LoggingNotificationChannel, NullNotificationChannel,
        )

        repo = _repo(tmp_path)
        _seed_alert(repo)
        composite = CompositeNotificationChannel(
            [NullNotificationChannel(), LoggingNotificationChannel()], repository=repo, max_attempts=3,
        )
        service = AlertDeliveryService(repo, composite, max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 1
        assert repo.fetch_alert_channel_deliveries("alert-1")[0].status == AlertStatus.DELIVERED

    def test_composite_with_a_failing_placeholder_channel_keeps_alert_pending(self, tmp_path):
        from src.paper_trading.notification_channels import (
            CompositeNotificationChannel, EmailNotificationChannel, NullNotificationChannel,
        )

        repo = _repo(tmp_path)
        _seed_alert(repo)
        composite = CompositeNotificationChannel(
            [NullNotificationChannel(), EmailNotificationChannel()], repository=repo, max_attempts=3,
        )
        service = AlertDeliveryService(repo, composite, max_attempts=3)
        result = service.deliver_pending_alerts()
        assert result.failed_count == 1
        alert = repo.get_inspection_alert_by_deduplication_key("key-1")
        assert alert.status == AlertStatus.PENDING

    def test_composite_does_not_resend_to_already_delivered_channel_on_retry(self, tmp_path):
        from src.paper_trading.notification_channels import CompositeNotificationChannel, NullNotificationChannel

        repo = _repo(tmp_path)
        _seed_alert(repo)

        class CountingChannel:
            def __init__(self):
                self.calls = 0

            def deliver(self, alert):
                self.calls += 1
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        good = CountingChannel()
        flaky_calls = {"n": 0}

        class FlakyChannel:
            def deliver(self, alert):
                flaky_calls["n"] += 1
                if flaky_calls["n"] < 2:
                    return AlertDeliveryResult(success=False, error_message="not yet", delivered_at=_now())
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        composite = CompositeNotificationChannel([good, FlakyChannel()], repository=repo, max_attempts=3)
        service = AlertDeliveryService(repo, composite, max_attempts=3)

        service.deliver_pending_alerts()
        service.deliver_pending_alerts()

        assert good.calls == 1  # nunca se reenvía al canal ya exitoso
        assert flaky_calls["n"] == 2
        assert repo.get_inspection_alert_by_deduplication_key("key-1").status == AlertStatus.DELIVERED
