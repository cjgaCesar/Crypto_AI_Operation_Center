"""
Pruebas para AlertDeliveryService (Etapa 6.9, ampliado en 6.10 para
depender de InspectionNotificationChannel, y en 6.11 para depender de
InspectionNotificationTemplate): entrega de alertas PENDING con
reintentos acotados. Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9/§24/§26.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus, AlertType, InspectionAlert
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.models import CashBalance, Order
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
from src.paper_trading.notification_templates import DefaultInspectionNotificationTemplate, NotificationMessage
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

    def deliver(self, message):
        self.delivered_alerts.append(message.alert_id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class FailingSink:
    def deliver(self, message):
        return AlertDeliveryResult(success=False, error_message="sink failure", delivered_at=_now())


class RaisingSink:
    def deliver(self, message):
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
            def deliver(self, message):
                if message.alert_id == "alert-0":
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

    def test_composite_with_a_failing_channel_keeps_alert_pending(self, tmp_path):
        """Etapa 6.15 (§30): antes usaba `WebhookNotificationChannel()`
        sin argumentos como doble de "canal que siempre falla" (era el
        último placeholder); ahora que Webhook es un canal real que
        exige un `transport`, se reemplaza por `FailingSink` (ya
        definido en este archivo), que preserva exactamente el mismo
        comportamiento que esta prueba necesita: un canal que siempre
        falla de forma controlada (nunca lanza)."""
        from src.paper_trading.notification_channels import CompositeNotificationChannel, NullNotificationChannel

        repo = _repo(tmp_path)
        _seed_alert(repo)
        composite = CompositeNotificationChannel(
            [NullNotificationChannel(), FailingSink()], repository=repo, max_attempts=3,
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

            def deliver(self, message):
                self.calls += 1
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        good = CountingChannel()
        flaky_calls = {"n": 0}

        class FlakyChannel:
            def deliver(self, message):
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


class TestUsesInjectedTemplate:
    """Etapa 6.11 (§26): AlertDeliveryService nunca construye el
    contenido del mensaje él mismo -- delega en `template.render()` y
    pasa el resultado, sin modificarlo, a `channel.deliver()`."""

    def test_default_template_is_the_default_inspection_notification_template(self, tmp_path):
        repo = _repo(tmp_path)
        service = AlertDeliveryService(repo, SucceedingSink(), max_attempts=3)
        assert isinstance(service._template, DefaultInspectionNotificationTemplate)


class TestTemplateExceptionIsControlled:
    """Etapa 6.11.1 (§26.x): una excepción de template.render() se trata
    exactamente igual que una excepción de canal -- nunca se propaga,
    nunca invoca ningún canal, y el resto del lote sigue procesándose."""

    def test_two_pending_alerts_both_survive_a_raising_template(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-a", dedup_key="dedup-a", run_id="run-a")
        _seed_alert(repo, alert_id="alert-b", dedup_key="dedup-b", run_id="run-b")

        class RaisingTemplate:
            def render(self, alert):
                raise RuntimeError("template failure")

        spy = SucceedingSink()
        try:
            service = AlertDeliveryService(repo, spy, max_attempts=3, template=RaisingTemplate())
            result = service.deliver_pending_alerts()
        except Exception as exc:
            pytest.fail(f"deliver_pending_alerts() must never propagate a template exception: {exc!r}")

        assert result.failed_count == 2
        alert_a = repo.get_inspection_alert_by_deduplication_key("dedup-a")
        alert_b = repo.get_inspection_alert_by_deduplication_key("dedup-b")
        for alert in (alert_a, alert_b):
            assert alert.delivery_attempts == 1
            assert alert.status == AlertStatus.PENDING
            assert "template failure" in alert.last_error
        assert spy.delivered_alerts == []  # el canal nunca se invoca

    def test_raising_template_reaches_failed_at_max_attempts(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-a", dedup_key="dedup-a", run_id="run-a")
        _seed_alert(repo, alert_id="alert-b", dedup_key="dedup-b", run_id="run-b")

        class RaisingTemplate:
            def render(self, alert):
                raise RuntimeError("template failure")

        spy = SucceedingSink()
        service = AlertDeliveryService(repo, spy, max_attempts=2, template=RaisingTemplate())

        service.deliver_pending_alerts()
        service.deliver_pending_alerts()

        alert_a = repo.get_inspection_alert_by_deduplication_key("dedup-a")
        alert_b = repo.get_inspection_alert_by_deduplication_key("dedup-b")
        for alert in (alert_a, alert_b):
            assert alert.status == AlertStatus.FAILED
            assert alert.delivery_attempts == 2
        assert spy.delivered_alerts == []

        # ninguna alerta ya FAILED se vuelve a procesar.
        result = service.deliver_pending_alerts()
        assert result.delivered_count == 0
        assert result.failed_count == 0


class TestTemplateReturnsInvalidType:
    """Etapa 6.11.1 (§26.x): si render() no devuelve un NotificationMessage,
    AlertDeliveryService lo detecta antes de invocar cualquier canal."""

    @pytest.mark.parametrize("bad_value", [None, "texto", 123])
    def test_invalid_return_value_is_a_controlled_failure(self, tmp_path, bad_value):
        repo = _repo(tmp_path)
        _seed_alert(repo)

        class BadTemplate:
            def render(self, alert):
                return bad_value

        spy = SucceedingSink()
        service = AlertDeliveryService(repo, spy, max_attempts=3, template=BadTemplate())
        result = service.deliver_pending_alerts()

        assert result.failed_count == 1
        alert = repo.get_inspection_alert_by_deduplication_key("key-1")
        assert alert.status == AlertStatus.PENDING
        assert alert.delivery_attempts == 1
        assert "NotificationMessage" in alert.last_error
        assert spy.delivered_alerts == []

    def test_invalid_return_value_reaches_failed_at_max_attempts(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)

        class BadTemplate:
            def render(self, alert):
                return None

        spy = SucceedingSink()
        service = AlertDeliveryService(repo, spy, max_attempts=2, template=BadTemplate())
        service.deliver_pending_alerts()
        service.deliver_pending_alerts()

        alert = repo.get_inspection_alert_by_deduplication_key("key-1")
        assert alert.status == AlertStatus.FAILED
        assert alert.delivery_attempts == 2
        assert spy.delivered_alerts == []

    def test_other_alerts_in_the_batch_continue_despite_invalid_template_return(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-bad", dedup_key="dedup-bad", run_id="run-bad")
        _seed_alert(repo, alert_id="alert-good", dedup_key="dedup-good", run_id="run-good")

        class SelectivelyBadTemplate:
            def render(self, alert):
                if alert.id == "alert-bad":
                    return "not a message"
                return DefaultInspectionNotificationTemplate().render(alert)

        spy = SucceedingSink()
        service = AlertDeliveryService(repo, spy, max_attempts=3, template=SelectivelyBadTemplate())
        result = service.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert result.failed_count == 1
        assert repo.get_inspection_alert_by_deduplication_key("dedup-good").status == AlertStatus.DELIVERED
        assert repo.get_inspection_alert_by_deduplication_key("dedup-bad").status == AlertStatus.PENDING
        assert spy.delivered_alerts == ["alert-good"]


class TestTemplateReturnsWrongAlertId:
    """Etapa 6.11.1 (§26.x, punto obligatorio): un NotificationMessage
    con alert_id distinto al de la InspectionAlert real nunca llega a
    invocar ningún canal ni a crear ninguna fila de estado por canal."""

    def test_mismatched_alert_id_is_a_controlled_failure(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-real", dedup_key="dedup-real")

        class WrongIdTemplate:
            def render(self, alert):
                return NotificationMessage(alert_id="otro-id", title="T", body="B", severity=None)

        spy = SucceedingSink()
        service = AlertDeliveryService(repo, spy, max_attempts=3, template=WrongIdTemplate())
        result = service.deliver_pending_alerts()

        assert result.failed_count == 1
        alert = repo.get_inspection_alert_by_deduplication_key("dedup-real")
        assert alert.status == AlertStatus.PENDING
        assert alert.delivery_attempts == 1
        assert "alert_id" in alert.last_error
        assert spy.delivered_alerts == []  # el canal nunca se invoca

    def test_mismatched_alert_id_never_creates_a_per_channel_row(self, tmp_path):
        from src.paper_trading.notification_channels import CompositeNotificationChannel

        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-real", dedup_key="dedup-real")

        class WrongIdTemplate:
            def render(self, alert):
                return NotificationMessage(alert_id="otro-id", title="T", body="B", severity=None)

        composite = CompositeNotificationChannel([SucceedingSink()], repository=repo, max_attempts=3)
        service = AlertDeliveryService(repo, composite, max_attempts=3, template=WrongIdTemplate())
        service.deliver_pending_alerts()

        assert repo.get_alert_channel_delivery("otro-id", "SucceedingSink") is None
        assert repo.get_alert_channel_delivery("alert-real", "SucceedingSink") is None
        assert repo.fetch_alert_channel_deliveries("alert-real") == []

    def test_mismatched_alert_id_reaches_failed_at_max_attempts(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-real", dedup_key="dedup-real")

        class WrongIdTemplate:
            def render(self, alert):
                return NotificationMessage(alert_id="otro-id", title="T", body="B", severity=None)

        service = AlertDeliveryService(repo, SucceedingSink(), max_attempts=2, template=WrongIdTemplate())
        service.deliver_pending_alerts()
        service.deliver_pending_alerts()

        alert = repo.get_inspection_alert_by_deduplication_key("dedup-real")
        assert alert.status == AlertStatus.FAILED
        assert alert.delivery_attempts == 2

    def test_other_alerts_continue_despite_mismatched_alert_id(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, alert_id="alert-bad", dedup_key="dedup-bad", run_id="run-bad")
        _seed_alert(repo, alert_id="alert-good", dedup_key="dedup-good", run_id="run-good")

        class SelectivelyWrongIdTemplate:
            def render(self, alert):
                if alert.id == "alert-bad":
                    return NotificationMessage(alert_id="otro-id", title="T", body="B", severity=None)
                return DefaultInspectionNotificationTemplate().render(alert)

        spy = SucceedingSink()
        service = AlertDeliveryService(repo, spy, max_attempts=3, template=SelectivelyWrongIdTemplate())
        result = service.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert result.failed_count == 1
        assert repo.get_inspection_alert_by_deduplication_key("dedup-good").status == AlertStatus.DELIVERED
        assert repo.get_inspection_alert_by_deduplication_key("dedup-bad").status == AlertStatus.PENDING


class TestIdempotencyUnaffectedByAlertIdFieldChange:
    """Etapa 6.11.1 (§26.x): mover alert_id de metadata a un campo
    explícito no altera la idempotencia por canal ya establecida en la
    Etapa 6.10.1."""

    def test_channel_a_succeeds_once_channel_b_retries_then_succeeds_across_restart(self, tmp_path):
        from src.paper_trading.notification_channels import CompositeNotificationChannel

        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        _seed_alert(repo1)

        class ChannelA:
            invocations = 0

            def deliver(self, message):
                ChannelA.invocations += 1
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        class ChannelB:
            invocations = 0

            def deliver(self, message):
                ChannelB.invocations += 1
                if ChannelB.invocations <= 2:
                    return AlertDeliveryResult(success=False, error_message="not yet", delivered_at=_now())
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        composite1 = CompositeNotificationChannel([ChannelA(), ChannelB()], repository=repo1, max_attempts=5)
        service1 = AlertDeliveryService(repo1, composite1, max_attempts=5)
        service1.deliver_pending_alerts()
        service1.deliver_pending_alerts()

        # Reinicio: nueva instancia de repositorio + servicios sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([ChannelA(), ChannelB()], repository=repo2, max_attempts=5)
        service2 = AlertDeliveryService(repo2, composite2, max_attempts=5)
        service2.deliver_pending_alerts()

        assert ChannelA.invocations == 1
        assert ChannelB.invocations == 3
        assert repo2.get_inspection_alert_by_deduplication_key("key-1").status == AlertStatus.DELIVERED

    def test_channel_receives_exactly_what_the_template_rendered(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo)

        rendered = NotificationMessage(
            alert_id="alert-1", title="titulo-fijo", body="cuerpo-fijo", severity=None,
        )

        class RecordingTemplate:
            def __init__(self):
                self.rendered_alerts = []

            def render(self, alert):
                self.rendered_alerts.append(alert.id)
                return rendered

        class RecordingChannel:
            def __init__(self):
                self.received = []

            def deliver(self, message):
                self.received.append(message)
                return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())

        template = RecordingTemplate()
        channel = RecordingChannel()
        service = AlertDeliveryService(repo, channel, max_attempts=3, template=template)
        service.deliver_pending_alerts()

        assert template.rendered_alerts == ["alert-1"]
        assert channel.received == [rendered]

    def test_service_never_builds_message_content_itself(self):
        """AlertDeliveryService no debe formatear texto de alertas: nunca
        una referencia a NotificationMessage() construida directamente
        dentro de su propio código (esa responsabilidad es exclusiva de
        la plantilla)."""
        import src.paper_trading.alert_delivery_service as module

        source = open(module.__file__, encoding="utf-8").read()
        assert "NotificationMessage(" not in source
