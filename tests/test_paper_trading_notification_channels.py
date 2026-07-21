"""
Pruebas para src/paper_trading/notification_channels.py (Etapa 6.10,
ampliado en 6.10.1 con idempotencia de entrega por canal):
patrón Strategy para la entrega de alertas de inspección.
Ver docs/ARQUITECTURA_PAPER_TRADING.md §24/§25.
"""

from datetime import datetime, timezone

import pytest

from src.paper_trading.alert_models import AlertDeliveryResult, AlertType, AlertStatus, InspectionAlert
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.notification_channels import (
    CompositeNotificationChannel, EmailNotificationChannel, LoggingNotificationChannel,
    NullNotificationChannel, SlackNotificationChannel, TelegramNotificationChannel,
    WebhookNotificationChannel,
)
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    return repo


def _alert(**overrides) -> InspectionAlert:
    defaults = dict(
        id="alert-1", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
        issue_code=None, severity=None, title="t", message="m", deduplication_key="k1",
        status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
    )
    defaults.update(overrides)
    return InspectionAlert(**defaults)


def _seed_alert(repo, alert) -> None:
    run = ScheduledInspectionRun(
        id=alert.run_id, started_at=_now(), completed_at=_now(), success=True, report=None,
        previous_run_id=None, new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0,
        changed_issue_count=0, alert_count=1,
    )
    repo.save_inspection_run_transaction(run, [alert])


class AlwaysSucceedsChannel:
    def __init__(self, name="ok"):
        self.name = name
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class AlwaysFailsChannel:
    def __init__(self, name="fail"):
        self.name = name
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        return AlertDeliveryResult(success=False, error_message=f"{self.name} failed", delivered_at=_now())


class RaisingChannel:
    def __init__(self, name="raiser"):
        self.name = name
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        raise RuntimeError(f"{self.name} exploded")


class FailsNTimesThenSucceeds:
    def __init__(self, fail_count, name="flaky"):
        self.name = name
        self.calls = 0
        self._fail_count = fail_count

    def deliver(self, alert):
        self.calls += 1
        if self.calls <= self._fail_count:
            return AlertDeliveryResult(success=False, error_message=f"{self.name} attempt {self.calls}", delivered_at=_now())
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


# La identidad de un canal dentro de CompositeNotificationChannel es
# type(channel).__name__ (ver limitación documentada en notification_channels.py):
# dos "canales" independientes en una prueba deben ser clases distintas,
# igual que en producción (un flag = una clase, nunca dos instancias de
# la misma clase en el mismo Composite).
class AlwaysSucceedsChannelA:
    def __init__(self):
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class AlwaysSucceedsChannelB:
    def __init__(self):
        self.delivered = []

    def deliver(self, alert):
        self.delivered.append(alert.id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class TestLoggingChannel:
    def test_delivers_successfully(self):
        channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        result = channel.deliver(_alert())
        assert result.success is True
        assert result.delivered_at == _now()

    def test_uses_injected_clock(self):
        fixed = datetime(2030, 5, 5, tzinfo=timezone.utc)
        channel = LoggingNotificationChannel(clock=FixedClock(fixed))
        result = channel.deliver(_alert())
        assert result.delivered_at == fixed


class TestNullChannel:
    def test_always_succeeds(self):
        channel = NullNotificationChannel(clock=FixedClock(_now()))
        result = channel.deliver(_alert())
        assert result.success is True
        assert result.error_message is None


class TestPlaceholderChannelsRaiseNotImplemented:
    @pytest.mark.parametrize("channel_class", [
        EmailNotificationChannel, SlackNotificationChannel,
        TelegramNotificationChannel, WebhookNotificationChannel,
    ])
    def test_deliver_raises_not_implemented(self, channel_class):
        channel = channel_class()
        with pytest.raises(NotImplementedError):
            channel.deliver(_alert())

    @pytest.mark.parametrize("channel_class", [
        EmailNotificationChannel, SlackNotificationChannel,
        TelegramNotificationChannel, WebhookNotificationChannel,
    ])
    def test_error_message_is_clear(self, channel_class):
        channel = channel_class()
        with pytest.raises(NotImplementedError) as exc_info:
            channel.deliver(_alert())
        assert "etapa posterior" in str(exc_info.value)


class TestCompositeConstructorValidation:
    def test_max_attempts_must_be_positive(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(ValueError):
            CompositeNotificationChannel([], repository=repo, max_attempts=0)


class TestCompositeChannelBothSucceed:
    def test_both_channels_executed_and_overall_success(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, _alert())
        channel1 = AlwaysSucceedsChannelA()
        channel2 = AlwaysSucceedsChannelB()
        composite = CompositeNotificationChannel([channel1, channel2], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert result.success is True


class TestCompositeChannelOneFailsOtherRuns:
    def test_channel_1_fails_channel_2_still_executes(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, _alert())
        channel1 = AlwaysFailsChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        composite = CompositeNotificationChannel([channel1, channel2], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert result.success is False
        assert "c1 failed" in result.error_message

    def test_channel_1_raises_channel_2_still_executes(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, _alert())
        channel1 = RaisingChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        composite = CompositeNotificationChannel([channel1, channel2], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert result.success is False
        assert "c1 exploded" in result.error_message
        # Correción 1 (§25.1): la excepción directa se persiste por canal.
        state = repo.get_alert_channel_delivery("alert-1", "RaisingChannel")
        assert state.delivery_attempts == 1
        assert "c1 exploded" in state.last_error


class TestCompositeChannelThreeChannelsTwoFailOneWorks:
    def test_all_three_are_attempted(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, _alert())
        channel1 = AlwaysFailsChannel("c1")
        channel2 = AlwaysSucceedsChannel("c2")
        channel3 = RaisingChannel("c3")
        composite = CompositeNotificationChannel(
            [channel1, channel2, channel3], repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        result = composite.deliver(_alert())
        assert channel1.delivered == ["alert-1"]
        assert channel2.delivered == ["alert-1"]
        assert channel3.delivered == ["alert-1"]
        assert result.success is False
        assert "c1 failed" in result.error_message
        assert "c3 exploded" in result.error_message


class TestCompositeChannelEmpty:
    def test_no_channels_is_a_successful_noop(self, tmp_path):
        repo = _repo(tmp_path)
        composite = CompositeNotificationChannel([], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_alert())
        assert result.success is True
        assert result.error_message is None


class TestCompositeChannelNeverRaises:
    def test_placeholder_channel_inside_composite_never_propagates(self, tmp_path):
        repo = _repo(tmp_path)
        _seed_alert(repo, _alert())
        composite = CompositeNotificationChannel(
            [EmailNotificationChannel(), NullNotificationChannel(clock=FixedClock(_now()))],
            repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        result = composite.deliver(_alert())  # no debe lanzar NotImplementedError
        assert result.success is False
        assert "EmailNotificationChannel" in result.error_message


class TestPerChannelIdempotency:
    """Tests mínimos nuevos (Etapa 6.10.1): entrega por canal."""

    def test_two_successful_channels_each_invoked_once(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        c1, c2 = AlwaysSucceedsChannelA(), AlwaysSucceedsChannelB()
        composite = CompositeNotificationChannel([c1, c2], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(alert)
        composite.deliver(alert)  # segunda pasada: no debería reinvocar a ninguno
        assert c1.delivered == ["alert-1"]
        assert c2.delivered == ["alert-1"]

    def test_successful_channel_is_not_repeated_only_failed_is_retried(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        good = AlwaysSucceedsChannel("good")
        flaky = FailsNTimesThenSucceeds(fail_count=1, name="flaky")
        composite = CompositeNotificationChannel([good, flaky], repository=repo, max_attempts=3, clock=FixedClock(_now()))

        result1 = composite.deliver(alert)
        assert good.delivered == ["alert-1"]
        assert flaky.calls == 1
        assert result1.success is False

        result2 = composite.deliver(alert)
        assert good.delivered == ["alert-1"]  # no se repite
        assert flaky.calls == 2  # solo el fallido se reintenta
        assert result2.success is True

    def test_restart_preserves_delivered_channel_state(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        alert = _alert()
        _seed_alert(repo1, alert)
        good = AlwaysSucceedsChannel("good")
        composite1 = CompositeNotificationChannel([good], repository=repo1, max_attempts=3, clock=FixedClock(_now()))
        composite1.deliver(alert)
        assert good.delivered == ["alert-1"]

        # "Reinicio": nueva instancia de repositorio + composite sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([good], repository=repo2, max_attempts=3, clock=FixedClock(_now()))
        composite2.deliver(alert)
        assert good.delivered == ["alert-1"]  # sigue sin repetirse tras el reinicio

    def test_channel_reaches_failed_when_attempts_exhausted(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        always_fails = AlwaysFailsChannel("bad")
        composite = CompositeNotificationChannel([always_fails], repository=repo, max_attempts=2, clock=FixedClock(_now()))

        result1 = composite.deliver(alert)
        assert result1.terminal is False
        state1 = repo.get_alert_channel_delivery("alert-1", "AlwaysFailsChannel")
        assert state1.status == AlertStatus.PENDING

        result2 = composite.deliver(alert)
        assert result2.terminal is True
        state2 = repo.get_alert_channel_delivery("alert-1", "AlwaysFailsChannel")
        assert state2.status == AlertStatus.FAILED

        # Un tercer intento no vuelve a invocar el canal ya FAILED (terminal).
        result3 = composite.deliver(alert)
        assert always_fails.delivered == ["alert-1", "alert-1"]  # 2 invocaciones, no 3
        assert result3.terminal is True

    def test_all_channels_delivered_marks_overall_success(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        c1, c2, c3 = AlwaysSucceedsChannel("c1"), AlwaysSucceedsChannel("c2"), AlwaysSucceedsChannel("c3")
        composite = CompositeNotificationChannel([c1, c2, c3], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(alert)
        assert result.success is True
        assert result.terminal is False

    def test_direct_exception_is_persisted_and_counted(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        raiser = RaisingChannel("boom")
        composite = CompositeNotificationChannel([raiser], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(alert)
        state = repo.get_alert_channel_delivery("alert-1", "RaisingChannel")
        assert state.delivery_attempts == 1
        assert "boom exploded" in state.last_error
        assert state.status == AlertStatus.PENDING

    def test_execution_order_follows_configured_list_for_pending_channels(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        order: list = []

        def _make_tracking_channel(label):
            class _TrackingChannel:
                def deliver(self, alert):
                    order.append(label)
                    return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())
            _TrackingChannel.__name__ = f"TrackingChannel{label}"
            return _TrackingChannel()

        c_a, c_b, c_c = _make_tracking_channel("A"), _make_tracking_channel("B"), _make_tracking_channel("C")
        composite = CompositeNotificationChannel([c_a, c_b, c_c], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(alert)
        assert order == ["A", "B", "C"]

    def test_empty_or_all_disabled_channels_is_explicit_success(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        composite = CompositeNotificationChannel([], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(alert)
        assert result.success is True
        assert result.error_message is None
        # Sin canales, no se persiste ningún estado por canal.
        assert repo.fetch_alert_channel_deliveries("alert-1") == []

    def test_bases_sqlite_anteriores_migran_sin_perder_datos(self, tmp_path):
        """Compatibilidad con bases anteriores a la Etapa 6.10.1: init()
        crea la nueva tabla de forma idempotente sin perder ningún dato ya
        persistido de alertas/corridas."""
        db_path = str(tmp_path / "test.db")
        repo = SQLitePaperTradingRepository(db_path)
        repo.init()
        alert = _alert()
        _seed_alert(repo, alert)

        # Simula un reinicio tras "actualizar" el código (init() de nuevo).
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        repo2.init()  # idempotente
        fetched = repo2.get_inspection_alert_by_deduplication_key("k1")
        assert fetched.id == "alert-1"
        assert repo2.fetch_alert_channel_deliveries("alert-1") == []


class TestConstructorSignatureCompatibility:
    """Etapa 6.10.1 (§25.4): `channel` queda como nombre oficial del
    parámetro; `sink=` no se restaura (sin uso interno, confirmado por
    auditoría). Esta prueba fija la firma actual para detectar cualquier
    cambio accidental futuro."""

    def test_current_signature_is_repository_channel_max_attempts_clock(self):
        import inspect
        from src.paper_trading.alert_delivery_service import AlertDeliveryService

        params = list(inspect.signature(AlertDeliveryService.__init__).parameters)
        assert params == ["self", "repository", "channel", "max_attempts", "clock"]

    def test_sink_keyword_no_longer_works(self, tmp_path):
        from src.paper_trading.alert_delivery_service import AlertDeliveryService

        repo = _repo(tmp_path)
        with pytest.raises(TypeError):
            AlertDeliveryService(repository=repo, sink=NullNotificationChannel(), max_attempts=3)

    def test_channel_keyword_works(self, tmp_path):
        from src.paper_trading.alert_delivery_service import AlertDeliveryService

        repo = _repo(tmp_path)
        service = AlertDeliveryService(repository=repo, channel=NullNotificationChannel(), max_attempts=3)
        assert service is not None


class TestLegacyAliasesStillWork:
    """Etapa 6.10.1 (§25.4): LoggingInspectionAlertSink/NullInspectionAlertSink
    (Etapa 6.9) se conservan como alias directos, sin duplicar la
    implementación."""

    def test_logging_alias_is_the_same_class(self):
        from src.paper_trading.alert_sink import LoggingInspectionAlertSink

        assert LoggingInspectionAlertSink is LoggingNotificationChannel

    def test_null_alias_is_the_same_class(self):
        from src.paper_trading.alert_sink import NullInspectionAlertSink

        assert NullInspectionAlertSink is NullNotificationChannel

    def test_alias_constructor_and_behavior_unchanged(self):
        from src.paper_trading.alert_sink import NullInspectionAlertSink

        channel = NullInspectionAlertSink(clock=FixedClock(_now()))
        result = channel.deliver(_alert())
        assert result.success is True
        assert result.delivered_at == _now()
