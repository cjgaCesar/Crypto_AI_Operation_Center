"""
Pruebas para src/paper_trading/notification_channels.py (Etapa 6.10,
ampliado en 6.10.1 con idempotencia de entrega por canal, en 6.11 para
transportar NotificationMessage en vez de InspectionAlert, y en 6.12
con el canal real de Telegram): patrón Strategy para la entrega de
alertas de inspección. Ver docs/ARQUITECTURA_PAPER_TRADING.md §24/§25/§26/§27.
"""

from datetime import datetime, timezone

import pytest

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_models import AlertDeliveryResult, AlertType, AlertStatus, InspectionAlert
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.notification_channels import (
    TELEGRAM_MAX_MESSAGE_LENGTH, CompositeNotificationChannel, EmailNotificationChannel,
    LoggingNotificationChannel, NullNotificationChannel, SlackNotificationChannel,
    TelegramNotificationChannel, WebhookNotificationChannel, _format_telegram_text,
)
from src.paper_trading.notification_templates import DefaultInspectionNotificationTemplate, NotificationMessage
from src.paper_trading.reconciliation_models import IssueSeverity
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.paper_trading.telegram_transport import TelegramTransportError


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


def _message(**overrides) -> NotificationMessage:
    """NotificationMessage aislado, para pruebas de canales que no
    necesitan pasar por la plantilla real. `alert_id` por defecto
    coincide con `_alert()` (ambas "alert-1"), para que
    CompositeNotificationChannel pueda persistir su idempotencia por
    canal contra un alert_id que además exista en la tabla de alertas
    (FOREIGN KEY)."""
    defaults = dict(alert_id="alert-1", title="t", body="m", severity=None, metadata={})
    defaults.update(overrides)
    return NotificationMessage(**defaults)


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

    def deliver(self, message):
        self.delivered.append(message.alert_id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class AlwaysFailsChannel:
    def __init__(self, name="fail"):
        self.name = name
        self.delivered = []

    def deliver(self, message):
        self.delivered.append(message.alert_id)
        return AlertDeliveryResult(success=False, error_message=f"{self.name} failed", delivered_at=_now())


class RaisingChannel:
    def __init__(self, name="raiser"):
        self.name = name
        self.delivered = []

    def deliver(self, message):
        self.delivered.append(message.alert_id)
        raise RuntimeError(f"{self.name} exploded")


class FailsNTimesThenSucceeds:
    def __init__(self, fail_count, name="flaky"):
        self.name = name
        self.calls = 0
        self._fail_count = fail_count

    def deliver(self, message):
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

    def deliver(self, message):
        self.delivered.append(message.alert_id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class AlwaysSucceedsChannelB:
    def __init__(self):
        self.delivered = []

    def deliver(self, message):
        self.delivered.append(message.alert_id)
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())


class TestLoggingChannel:
    def test_delivers_successfully(self):
        channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        result = channel.deliver(_message())
        assert result.success is True
        assert result.delivered_at == _now()

    def test_uses_injected_clock(self):
        fixed = datetime(2030, 5, 5, tzinfo=timezone.utc)
        channel = LoggingNotificationChannel(clock=FixedClock(fixed))
        result = channel.deliver(_message())
        assert result.delivered_at == fixed


class TestNullChannel:
    def test_always_succeeds(self):
        channel = NullNotificationChannel(clock=FixedClock(_now()))
        result = channel.deliver(_message())
        assert result.success is True
        assert result.error_message is None


class TestPlaceholderChannelsRaiseNotImplemented:
    """Etapa 6.12 (§27): TelegramNotificationChannel deja de ser
    placeholder -- ya no aparece en esta lista, tiene sus propias
    pruebas en TestTelegramNotificationChannel."""

    @pytest.mark.parametrize("channel_class", [
        EmailNotificationChannel, SlackNotificationChannel, WebhookNotificationChannel,
    ])
    def test_deliver_raises_not_implemented(self, channel_class):
        channel = channel_class()
        with pytest.raises(NotImplementedError):
            channel.deliver(_message())

    @pytest.mark.parametrize("channel_class", [
        EmailNotificationChannel, SlackNotificationChannel, WebhookNotificationChannel,
    ])
    def test_error_message_is_clear(self, channel_class):
        channel = channel_class()
        with pytest.raises(NotImplementedError) as exc_info:
            channel.deliver(_message())
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
        result = composite.deliver(_message())
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
        result = composite.deliver(_message())
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
        result = composite.deliver(_message())
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
        result = composite.deliver(_message())
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
        result = composite.deliver(_message())
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
        result = composite.deliver(_message())  # no debe lanzar NotImplementedError
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
        composite.deliver(_message())
        composite.deliver(_message())  # segunda pasada: no debería reinvocar a ninguno
        assert c1.delivered == ["alert-1"]
        assert c2.delivered == ["alert-1"]

    def test_successful_channel_is_not_repeated_only_failed_is_retried(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        good = AlwaysSucceedsChannel("good")
        flaky = FailsNTimesThenSucceeds(fail_count=1, name="flaky")
        composite = CompositeNotificationChannel([good, flaky], repository=repo, max_attempts=3, clock=FixedClock(_now()))

        result1 = composite.deliver(_message())
        assert good.delivered == ["alert-1"]
        assert flaky.calls == 1
        assert result1.success is False

        result2 = composite.deliver(_message())
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
        composite1.deliver(_message())
        assert good.delivered == ["alert-1"]

        # "Reinicio": nueva instancia de repositorio + composite sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([good], repository=repo2, max_attempts=3, clock=FixedClock(_now()))
        composite2.deliver(_message())
        assert good.delivered == ["alert-1"]  # sigue sin repetirse tras el reinicio

    def test_channel_reaches_failed_when_attempts_exhausted(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        always_fails = AlwaysFailsChannel("bad")
        composite = CompositeNotificationChannel([always_fails], repository=repo, max_attempts=2, clock=FixedClock(_now()))

        result1 = composite.deliver(_message())
        assert result1.terminal is False
        state1 = repo.get_alert_channel_delivery("alert-1", "AlwaysFailsChannel")
        assert state1.status == AlertStatus.PENDING

        result2 = composite.deliver(_message())
        assert result2.terminal is True
        state2 = repo.get_alert_channel_delivery("alert-1", "AlwaysFailsChannel")
        assert state2.status == AlertStatus.FAILED

        # Un tercer intento no vuelve a invocar el canal ya FAILED (terminal).
        result3 = composite.deliver(_message())
        assert always_fails.delivered == ["alert-1", "alert-1"]  # 2 invocaciones, no 3
        assert result3.terminal is True

    def test_all_channels_delivered_marks_overall_success(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        c1, c2, c3 = AlwaysSucceedsChannel("c1"), AlwaysSucceedsChannel("c2"), AlwaysSucceedsChannel("c3")
        composite = CompositeNotificationChannel([c1, c2, c3], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_message())
        assert result.success is True
        assert result.terminal is False

    def test_direct_exception_is_persisted_and_counted(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        raiser = RaisingChannel("boom")
        composite = CompositeNotificationChannel([raiser], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message())
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
                def deliver(self, message):
                    order.append(label)
                    return AlertDeliveryResult(success=True, error_message=None, delivered_at=_now())
            _TrackingChannel.__name__ = f"TrackingChannel{label}"
            return _TrackingChannel()

        c_a, c_b, c_c = _make_tracking_channel("A"), _make_tracking_channel("B"), _make_tracking_channel("C")
        composite = CompositeNotificationChannel([c_a, c_b, c_c], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message())
        assert order == ["A", "B", "C"]

    def test_empty_or_all_disabled_channels_is_explicit_success(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        composite = CompositeNotificationChannel([], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_message())
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
    auditoría). Etapa 6.11 (§26) agrega `template` al final (con default
    `DefaultInspectionNotificationTemplate()`), sin alterar ninguno de
    los parámetros anteriores. Esta prueba fija la firma actual para
    detectar cualquier cambio accidental futuro."""

    def test_current_signature_is_repository_channel_max_attempts_clock_template(self):
        import inspect
        from src.paper_trading.alert_delivery_service import AlertDeliveryService

        params = list(inspect.signature(AlertDeliveryService.__init__).parameters)
        assert params == ["self", "repository", "channel", "max_attempts", "clock", "template"]

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
        result = channel.deliver(_message())
        assert result.success is True
        assert result.delivered_at == _now()


class FakeTelegramTransport:
    """Doble de TelegramTransport: nunca realiza ninguna conexión real."""

    def __init__(self, fail_times: int = 0, error_message: str = "Telegram API returned an unsuccessful response."):
        self.calls: list = []
        self._fail_times = fail_times
        self._error_message = error_message

    def send_message(self, *, bot_token, chat_id, text, timeout_seconds):
        self.calls.append(dict(bot_token=bot_token, chat_id=chat_id, text=text, timeout_seconds=timeout_seconds))
        if len(self.calls) <= self._fail_times:
            raise TelegramTransportError(self._error_message)


class TestTelegramTextFormat:
    """Etapa 6.12 (§27): _format_telegram_text() es pura, determinista,
    nunca HTML/Markdown, nunca incluye metadata/alert_id."""

    def test_includes_title_and_body(self):
        message = NotificationMessage(alert_id="a1", title="Titulo", body="Cuerpo", severity=None)
        text = _format_telegram_text(message)
        assert "Titulo" in text
        assert "Cuerpo" in text

    def test_includes_severity_when_present(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        text = _format_telegram_text(message)
        assert "Severidad: CRITICAL" in text

    def test_omits_severity_line_when_none(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        text = _format_telegram_text(message)
        assert "Severidad" not in text

    def test_does_not_include_metadata_or_alert_id(self):
        message = NotificationMessage(
            alert_id="alert-secreto", title="T", body="B", severity=None,
            metadata={"run_id": "run-1", "alert_type": "NEW_ISSUE"},
        )
        text = _format_telegram_text(message)
        assert "alert-secreto" not in text
        assert "run-1" not in text
        assert "alert_type" not in text

    def test_never_contains_html_or_telegram_markdown(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        text = _format_telegram_text(message)
        for forbidden in ("<b>", "<i>", "*bold*", "_italic_", "```", "[link]("):
            assert forbidden not in text

    def test_is_deterministic(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        assert _format_telegram_text(message) == _format_telegram_text(message)


class TestTelegramTextLength:
    def test_short_text_is_not_altered(self):
        message = NotificationMessage(alert_id="a1", title="T", body="cuerpo corto", severity=None)
        text = _format_telegram_text(message)
        assert text == "T\n\ncuerpo corto"

    def test_text_at_exact_limit_is_not_truncated(self):
        body = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH - len("T\n\n"))
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_telegram_text(message)
        assert len(text) == TELEGRAM_MAX_MESSAGE_LENGTH
        assert "truncado" not in text

    def test_text_over_limit_is_truncated_with_mark(self):
        body = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH * 2)
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_telegram_text(message)
        assert len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH
        assert text.endswith("[Mensaje truncado]")

    def test_truncated_text_never_exceeds_max_length(self):
        body = "y" * (TELEGRAM_MAX_MESSAGE_LENGTH + 1)
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_telegram_text(message)
        assert len(text) == TELEGRAM_MAX_MESSAGE_LENGTH


class TestTelegramNotificationChannelConstructor:
    def test_requires_bot_token(self):
        with pytest.raises(ValueError):
            TelegramNotificationChannel(bot_token="", chat_id="c", transport=FakeTelegramTransport())

    def test_requires_chat_id(self):
        with pytest.raises(ValueError):
            TelegramNotificationChannel(bot_token="t", chat_id="", transport=FakeTelegramTransport())

    def test_rejects_blank_bot_token(self):
        with pytest.raises(ValueError):
            TelegramNotificationChannel(bot_token="   ", chat_id="c", transport=FakeTelegramTransport())

    def test_requires_positive_timeout(self):
        with pytest.raises(ValueError):
            TelegramNotificationChannel(bot_token="t", chat_id="c", transport=FakeTelegramTransport(), timeout_seconds=0)

    def test_rejects_negative_timeout(self):
        with pytest.raises(ValueError):
            TelegramNotificationChannel(
                bot_token="t", chat_id="c", transport=FakeTelegramTransport(), timeout_seconds=-1,
            )

    def test_valid_configuration_constructs_successfully(self):
        channel = TelegramNotificationChannel(bot_token="t", chat_id="c", transport=FakeTelegramTransport())
        assert channel is not None


class TestTelegramNotificationChannelDelivery:
    def test_successful_delivery_invokes_transport_once(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(bot_token="t", chat_id="c", transport=transport, clock=FixedClock(_now()))
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        result = channel.deliver(message)
        assert result.success is True
        assert len(transport.calls) == 1

    def test_uses_injected_clock_for_delivered_at(self):
        fixed = datetime(2030, 6, 6, tzinfo=timezone.utc)
        channel = TelegramNotificationChannel(
            bot_token="t", chat_id="c", transport=FakeTelegramTransport(), clock=FixedClock(fixed),
        )
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.delivered_at == fixed

    def test_does_not_modify_the_message(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(bot_token="t", chat_id="c", transport=transport)
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        channel.deliver(message)
        assert message == NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)

    def test_transport_receives_chat_id_and_bot_token(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(bot_token="secret-token", chat_id="chat-42", transport=transport)
        channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert transport.calls[0]["bot_token"] == "secret-token"
        assert transport.calls[0]["chat_id"] == "chat-42"
        assert transport.calls[0]["timeout_seconds"] == 10.0

    def test_transport_failure_returns_failed_result_without_raising(self):
        transport = FakeTelegramTransport(fail_times=99)
        channel = TelegramNotificationChannel(bot_token="secret-token", chat_id="c", transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False
        assert "secret-token" not in result.error_message

    def test_transport_failure_never_leaks_bot_token(self):
        transport = FakeTelegramTransport(fail_times=99, error_message="Telegram API request failed (HTTP 401).")
        channel = TelegramNotificationChannel(bot_token="MY-SUPER-SECRET", chat_id="c", transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert "MY-SUPER-SECRET" not in result.error_message

    def test_deliver_never_retries_internally(self):
        transport = FakeTelegramTransport(fail_times=1)
        channel = TelegramNotificationChannel(bot_token="t", chat_id="c", transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False
        assert len(transport.calls) == 1  # una sola solicitud por llamada a deliver()


class TestTelegramChannelIdentity:
    """Etapa 6.12 (§27, punto 14): la identidad persistente del canal
    sigue siendo type(channel).__name__ == 'TelegramNotificationChannel'."""

    def test_persisted_identity_is_the_class_name(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-tg", deduplication_key="k-tg")
        _seed_alert(repo, alert)
        transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(bot_token="t", chat_id="c", transport=transport, clock=FixedClock(_now()))
        composite = CompositeNotificationChannel([telegram_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message(alert_id="alert-tg"))
        state = repo.get_alert_channel_delivery("alert-tg", "TelegramNotificationChannel")
        assert state is not None
        assert state.status == AlertStatus.DELIVERED


class TestTelegramEndToEndWithoutInternet:
    """Punto 21: integración interna completa (repositorio real,
    DefaultInspectionNotificationTemplate real, TelegramNotificationChannel
    con FakeTelegramTransport, CompositeNotificationChannel,
    AlertDeliveryService), sin ninguna conexión real a internet."""

    def test_full_pipeline_delivers_and_never_resends(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()

        alert = InspectionAlert(
            id="alert-e2e", run_id="run-e2e", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
            issue_code=None, severity=None, title="t", message="Inconsistencia detectada.",
            deduplication_key="dedup-e2e", status=AlertStatus.PENDING, delivery_attempts=0,
            last_error=None, created_at=_now(),
        )
        _seed_alert(repo1, alert)

        transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(
            bot_token="t", chat_id="c", transport=transport, clock=FixedClock(_now()),
        )
        composite1 = CompositeNotificationChannel([telegram_channel], repository=repo1, max_attempts=3, clock=FixedClock(_now()))
        service1 = AlertDeliveryService(
            repo1, composite1, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )

        result = service1.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(transport.calls) == 1
        assert "Inconsistencia detectada." in transport.calls[0]["text"]
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-e2e").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-e2e", "TelegramNotificationChannel").status == AlertStatus.DELIVERED

        # Segundo procesamiento: no reenvía (ya no queda PENDING).
        service1.deliver_pending_alerts()
        assert len(transport.calls) == 1

        # "Reinicio": nueva instancia de repositorio + servicios sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([telegram_channel], repository=repo2, max_attempts=3, clock=FixedClock(_now()))
        service2 = AlertDeliveryService(
            repo2, composite2, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )
        service2.deliver_pending_alerts()
        assert len(transport.calls) == 1  # Telegram no se vuelve a invocar tras el reinicio.


class TestTelegramFailThenSucceed:
    """Punto 22: intento 1 falla, intento 2 tiene éxito."""

    def test_first_attempt_fails_second_succeeds(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-retry", deduplication_key="dedup-retry")
        _seed_alert(repo, alert)

        transport = FakeTelegramTransport(fail_times=1)
        telegram_channel = TelegramNotificationChannel(bot_token="t", chat_id="c", transport=transport, clock=FixedClock(_now()))
        good_channel = AlwaysSucceedsChannel("good")
        composite = CompositeNotificationChannel(
            [good_channel, telegram_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        service = AlertDeliveryService(repo, composite, max_attempts=3, clock=FixedClock(_now()))

        service.deliver_pending_alerts()
        telegram_state_1 = repo.get_alert_channel_delivery("alert-retry", "TelegramNotificationChannel")
        assert telegram_state_1.status == AlertStatus.PENDING
        assert repo.get_inspection_alert_by_deduplication_key("dedup-retry").status == AlertStatus.PENDING
        assert good_channel.delivered == ["alert-retry"]

        service.deliver_pending_alerts()
        telegram_state_2 = repo.get_alert_channel_delivery("alert-retry", "TelegramNotificationChannel")
        assert telegram_state_2.status == AlertStatus.DELIVERED
        assert repo.get_inspection_alert_by_deduplication_key("dedup-retry").status == AlertStatus.DELIVERED
        assert good_channel.delivered == ["alert-retry"]  # el canal exitoso nunca se repite
        assert len(transport.calls) == 2
