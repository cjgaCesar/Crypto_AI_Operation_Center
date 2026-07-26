"""
Pruebas para src/paper_trading/notification_channels.py (Etapa 6.10,
ampliado en 6.10.1 con idempotencia de entrega por canal, en 6.11 para
transportar NotificationMessage en vez de InspectionAlert, en 6.12 con
el canal real de Telegram, en 6.13 con el canal real de Slack, en 6.14
con el canal real de Email SMTP, y en 6.15 con el canal real de Webhook
HTTP genérico): patrón Strategy para la entrega de alertas de
inspección. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §24/§25/§26/§27/§28/§29/§30.
"""

import json
from datetime import datetime, timezone

import pytest

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_models import AlertDeliveryResult, AlertType, AlertStatus, InspectionAlert
from src.paper_trading.email_transport import EmailTransportError
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.notification_channels import (
    EMAIL_MAX_BODY_LENGTH, EMAIL_MAX_SUBJECT_LENGTH, SLACK_MAX_MESSAGE_LENGTH, TELEGRAM_MAX_MESSAGE_LENGTH,
    WEBHOOK_MAX_PAYLOAD_BYTES,
    CompositeNotificationChannel, EmailNotificationChannel, LoggingNotificationChannel, NullNotificationChannel,
    SlackNotificationChannel, TelegramNotificationChannel, WebhookNotificationChannel,
    _build_webhook_payload, _format_email_body, _format_email_subject, _format_slack_text, _format_telegram_text,
)
from src.paper_trading.notification_templates import DefaultInspectionNotificationTemplate, NotificationMessage
from src.paper_trading.reconciliation_models import IssueSeverity
from src.paper_trading.slack_transport import SlackTransportError
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.paper_trading.telegram_transport import TelegramTransportError
from src.paper_trading.webhook_transport import WebhookTransportError


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
    def test_raising_channel_inside_composite_never_propagates(self, tmp_path):
        """Etapa 6.15 (§30): antes usaba `WebhookNotificationChannel()`
        sin argumentos como doble de "canal que siempre lanza" (era el
        último placeholder); ahora que Webhook es un canal real que
        exige un `transport`, se reemplaza por `RaisingChannel` (ya
        definida en este archivo), que preserva exactamente el mismo
        comportamiento que esta prueba necesita."""
        repo = _repo(tmp_path)
        _seed_alert(repo, _alert())
        composite = CompositeNotificationChannel(
            [RaisingChannel("r"), NullNotificationChannel(clock=FixedClock(_now()))],
            repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        result = composite.deliver(_message())  # no debe lanzar RuntimeError
        assert result.success is False
        assert "RaisingChannel" in result.error_message


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
    """Doble de TelegramTransport (Etapa 6.12.1): nunca realiza ninguna
    conexión real. Ya no recibe ni conserva credenciales -- solo
    `text`, igual que el contrato real de `send_message()`."""

    def __init__(self, fail_times: int = 0, error_message: str = "Telegram API returned an unsuccessful response."):
        self.calls: list = []
        self._fail_times = fail_times
        self._error_message = error_message

    def send_message(self, *, text):
        self.calls.append(dict(text=text))
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


class TestTelegramFormatterPurity:
    """Etapa 6.12.1 (§27.x, punto 9/10): _format_telegram_text() depende
    exclusivamente de `message` y de constantes inmutables del módulo --
    nunca de clock, entorno, locale, red ni estado global."""

    def test_determinism_across_repeated_calls(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        result_1 = _format_telegram_text(message)
        result_2 = _format_telegram_text(message)
        assert result_1 == result_2

    def test_independent_of_any_clock(self):
        """El formatter no recibe ni consulta ningún Clock -- su firma
        (message) -> str no admite inyectar uno, y el resultado no
        depende de ningún reloj real ni simulado."""
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        import inspect

        params = list(inspect.signature(_format_telegram_text).parameters)
        assert params == ["message"]
        assert _format_telegram_text(message) == _format_telegram_text(message)

    def test_independent_of_environment_variables(self, monkeypatch):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        before = _format_telegram_text(message)

        for var, value in (
            ("TZ", "America/Argentina/Buenos_Aires"), ("LANG", "es_AR.UTF-8"), ("LC_ALL", "es_AR.UTF-8"),
            ("TELEGRAM_BOT_TOKEN", "deberia-ser-ignorado"), ("TELEGRAM_CHAT_ID", "deberia-ser-ignorado"),
        ):
            monkeypatch.setenv(var, value)

        after = _format_telegram_text(message)
        assert before == after

    def test_does_not_mutate_the_message(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        before = repr(message)
        _format_telegram_text(message)
        after = repr(message)
        assert before == after

    def test_has_no_side_effects_source_inspection(self):
        """Inspección estructural razonable (no basada en buscar
        substrings arbitrarios): el cuerpo de la función no importa ni
        referencia ningún módulo de red/filesystem/logging/persistencia."""
        import inspect

        source = inspect.getsource(_format_telegram_text)
        forbidden_identifiers = (
            "logger.", "logging.", "print(", "open(", "socket.", "urllib.", "requests.",
            "self._repository", "repository.", "os.environ", "os.getenv",
        )
        for forbidden in forbidden_identifiers:
            assert forbidden not in source


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
    """Etapa 6.12.1 (§27.x): el constructor ya no acepta bot_token/
    chat_id/timeout_seconds -- solo transport/clock."""

    def test_only_accepts_transport_and_clock(self):
        import inspect

        params = list(inspect.signature(TelegramNotificationChannel.__init__).parameters)
        assert params == ["self", "transport", "clock"]

    def test_bot_token_keyword_no_longer_works(self):
        with pytest.raises(TypeError):
            TelegramNotificationChannel(bot_token="t", transport=FakeTelegramTransport())

    def test_chat_id_keyword_no_longer_works(self):
        with pytest.raises(TypeError):
            TelegramNotificationChannel(chat_id="c", transport=FakeTelegramTransport())

    def test_timeout_seconds_keyword_no_longer_works(self):
        with pytest.raises(TypeError):
            TelegramNotificationChannel(timeout_seconds=5.0, transport=FakeTelegramTransport())

    def test_valid_configuration_constructs_successfully(self):
        channel = TelegramNotificationChannel(transport=FakeTelegramTransport())
        assert channel is not None


class TestTelegramNotificationChannelDelivery:
    def test_successful_delivery_invokes_transport_once(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(transport=transport, clock=FixedClock(_now()))
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        result = channel.deliver(message)
        assert result.success is True
        assert len(transport.calls) == 1

    def test_uses_injected_clock_for_delivered_at(self):
        fixed = datetime(2030, 6, 6, tzinfo=timezone.utc)
        channel = TelegramNotificationChannel(transport=FakeTelegramTransport(), clock=FixedClock(fixed))
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.delivered_at == fixed

    def test_does_not_modify_the_message(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(transport=transport)
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        channel.deliver(message)
        assert message == NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)

    def test_transport_receives_only_text(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(transport=transport)
        channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert list(transport.calls[0].keys()) == ["text"]
        assert transport.calls[0]["text"] == "T\n\nB"

    def test_channel_never_passes_credentials_to_transport(self):
        transport = FakeTelegramTransport()
        channel = TelegramNotificationChannel(transport=transport)
        channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert "bot_token" not in transport.calls[0]
        assert "chat_id" not in transport.calls[0]
        assert "timeout_seconds" not in transport.calls[0]

    def test_transport_failure_returns_failed_result_without_raising(self):
        transport = FakeTelegramTransport(fail_times=99)
        channel = TelegramNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False

    def test_transport_failure_message_passes_through_unmodified(self):
        """El canal nunca conoce credenciales, así que no puede
        agregarlas al error -- solo transmite el mensaje ya sanitizado
        que produjo el transporte."""
        transport = FakeTelegramTransport(fail_times=99, error_message="Telegram API request failed (HTTP 401).")
        channel = TelegramNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.error_message == "Telegram API request failed (HTTP 401)."

    def test_deliver_never_retries_internally(self):
        transport = FakeTelegramTransport(fail_times=1)
        channel = TelegramNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False
        assert len(transport.calls) == 1  # una sola solicitud por llamada a deliver()


class TestTelegramChannelHasNoCredentials:
    """Etapa 6.12.1 (§27.x): el canal no posee ningún atributo de
    credencial, ni siquiera indirectamente."""

    def test_channel_has_no_credential_attributes(self):
        channel = TelegramNotificationChannel(transport=FakeTelegramTransport())
        forbidden_attrs = ("_bot_token", "bot_token", "_chat_id", "chat_id", "_timeout_seconds", "timeout_seconds")
        for attr in forbidden_attrs:
            assert not hasattr(channel, attr), f"el canal no debería tener el atributo {attr!r}"

    def test_channel_only_has_transport_and_clock(self):
        channel = TelegramNotificationChannel(transport=FakeTelegramTransport())
        assert set(vars(channel).keys()) == {"_transport", "_clock"}

    def test_repr_does_not_contain_token(self):
        channel = TelegramNotificationChannel(transport=FakeTelegramTransport())
        assert "MY-SUPER-SECRET" not in repr(channel)

    def test_str_does_not_contain_token(self):
        channel = TelegramNotificationChannel(transport=FakeTelegramTransport())
        assert "MY-SUPER-SECRET" not in str(channel)


class TestTelegramChannelIdentity:
    """Etapa 6.12 (§27, punto 14): la identidad persistente del canal
    sigue siendo type(channel).__name__ == 'TelegramNotificationChannel'."""

    def test_persisted_identity_is_the_class_name(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-tg", deduplication_key="k-tg")
        _seed_alert(repo, alert)
        transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=transport, clock=FixedClock(_now()))
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
        telegram_channel = TelegramNotificationChannel(transport=transport, clock=FixedClock(_now()))
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
        telegram_channel = TelegramNotificationChannel(transport=transport, clock=FixedClock(_now()))
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


class FakeSlackTransport:
    """Doble de SlackTransport (Etapa 6.13): nunca realiza ninguna
    conexión real. Solo recibe `text`, igual que el contrato real de
    `send_message()`."""

    def __init__(self, fail_times: int = 0, error_message: str = "Slack webhook returned an unsuccessful response."):
        self.calls: list = []
        self._fail_times = fail_times
        self._error_message = error_message

    def send_message(self, *, text):
        self.calls.append(dict(text=text))
        if len(self.calls) <= self._fail_times:
            raise SlackTransportError(self._error_message)


class TestSlackTextFormat:
    """Etapa 6.13 (§28): _format_slack_text() es pura, determinista,
    nunca Block Kit, nunca incluye metadata/alert_id."""

    def test_includes_title_and_body(self):
        message = NotificationMessage(alert_id="a1", title="Titulo", body="Cuerpo", severity=None)
        text = _format_slack_text(message)
        assert "Titulo" in text
        assert "Cuerpo" in text

    def test_includes_severity_when_present(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        text = _format_slack_text(message)
        assert "Severidad: CRITICAL" in text

    def test_omits_severity_line_when_none(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        text = _format_slack_text(message)
        assert "Severidad" not in text

    def test_does_not_include_metadata_or_alert_id(self):
        message = NotificationMessage(
            alert_id="alert-secreto", title="T", body="B", severity=None,
            metadata={"run_id": "run-1", "alert_type": "NEW_ISSUE"},
        )
        text = _format_slack_text(message)
        assert "alert-secreto" not in text
        assert "run-1" not in text
        assert "alert_type" not in text

    def test_never_contains_block_kit_or_slack_specific_markup(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        text = _format_slack_text(message)
        for forbidden in ('"blocks":', '"attachments":', "*bold*", "_italic_", "```", "<http"):
            assert forbidden not in text

    def test_is_deterministic(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        assert _format_slack_text(message) == _format_slack_text(message)


class TestSlackMentionNeutralization:
    """Etapa 6.13 (§28, punto 15): las menciones globales de Slack se
    neutralizan con un carácter de ancho cero, para que nunca activen
    una notificación masiva real."""

    @pytest.mark.parametrize("mention", ["@channel", "@here", "@everyone"])
    def test_at_mentions_are_neutralized(self, mention):
        message = NotificationMessage(alert_id="a1", title="T", body=f"Aviso {mention} urgente", severity=None)
        text = _format_slack_text(message)
        assert mention not in text

    @pytest.mark.parametrize("mention", ["<!channel>", "<!here>", "<!everyone>"])
    def test_bang_mentions_are_neutralized(self, mention):
        message = NotificationMessage(alert_id="a1", title="T", body=f"Aviso {mention} urgente", severity=None)
        text = _format_slack_text(message)
        assert mention not in text

    def test_neutralized_text_remains_readable(self):
        message = NotificationMessage(alert_id="a1", title="T", body="Aviso @channel urgente", severity=None)
        text = _format_slack_text(message)
        assert "channel" in text
        assert "Aviso" in text
        assert "urgente" in text

    def test_normal_text_without_mentions_is_unmodified(self):
        message = NotificationMessage(alert_id="a1", title="T", body="Texto normal sin menciones.", severity=None)
        text = _format_slack_text(message)
        assert text == "T\n\nTexto normal sin menciones."


class TestSlackFormatterPurity:
    """Etapa 6.13 (§28): _format_slack_text() depende exclusivamente de
    `message` y de constantes inmutables del módulo -- nunca de clock,
    entorno, locale, red ni estado global (mismo criterio que Telegram,
    §27.x)."""

    def test_determinism_across_repeated_calls(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        assert _format_slack_text(message) == _format_slack_text(message)

    def test_signature_does_not_admit_a_clock(self):
        import inspect

        params = list(inspect.signature(_format_slack_text).parameters)
        assert params == ["message"]

    def test_independent_of_environment_variables(self, monkeypatch):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        before = _format_slack_text(message)

        for var, value in (
            ("TZ", "America/Argentina/Buenos_Aires"), ("LANG", "es_AR.UTF-8"), ("LC_ALL", "es_AR.UTF-8"),
            ("SLACK_WEBHOOK_URL", "https://hooks.slack.com/deberia-ser-ignorado"),
        ):
            monkeypatch.setenv(var, value)

        after = _format_slack_text(message)
        assert before == after

    def test_does_not_mutate_the_message(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        before = repr(message)
        _format_slack_text(message)
        after = repr(message)
        assert before == after

    def test_has_no_side_effects_source_inspection(self):
        import inspect

        source = inspect.getsource(_format_slack_text)
        forbidden_identifiers = (
            "logger.", "logging.", "print(", "open(", "socket.", "urllib.", "requests.",
            "self._repository", "repository.", "os.environ", "os.getenv",
        )
        for forbidden in forbidden_identifiers:
            assert forbidden not in source


class TestSlackTextLength:
    def test_short_text_is_not_altered(self):
        message = NotificationMessage(alert_id="a1", title="T", body="cuerpo corto", severity=None)
        text = _format_slack_text(message)
        assert text == "T\n\ncuerpo corto"

    def test_text_at_exact_limit_is_not_truncated(self):
        body = "x" * (SLACK_MAX_MESSAGE_LENGTH - len("T\n\n"))
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_slack_text(message)
        assert len(text) == SLACK_MAX_MESSAGE_LENGTH
        assert "truncado" not in text

    def test_text_over_limit_is_truncated_with_mark(self):
        body = "x" * (SLACK_MAX_MESSAGE_LENGTH * 2)
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_slack_text(message)
        assert len(text) <= SLACK_MAX_MESSAGE_LENGTH
        assert text.endswith("[Mensaje truncado]")

    def test_truncated_text_never_exceeds_max_length(self):
        body = "y" * (SLACK_MAX_MESSAGE_LENGTH + 1)
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_slack_text(message)
        assert len(text) == SLACK_MAX_MESSAGE_LENGTH


class TestSlackNotificationChannelConstructor:
    """Etapa 6.13 (§28): el constructor solo acepta transport/clock."""

    def test_only_accepts_transport_and_clock(self):
        import inspect

        params = list(inspect.signature(SlackNotificationChannel.__init__).parameters)
        assert params == ["self", "transport", "clock"]

    def test_webhook_url_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            SlackNotificationChannel(webhook_url="https://hooks.slack.com/x", transport=FakeSlackTransport())

    def test_timeout_seconds_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            SlackNotificationChannel(timeout_seconds=5.0, transport=FakeSlackTransport())

    def test_valid_configuration_constructs_successfully(self):
        channel = SlackNotificationChannel(transport=FakeSlackTransport())
        assert channel is not None


class TestSlackChannelHasNoCredentials:
    def test_channel_has_no_credential_attributes(self):
        channel = SlackNotificationChannel(transport=FakeSlackTransport())
        for attr in ("_webhook_url", "webhook_url", "_timeout_seconds", "timeout_seconds", "_config", "config"):
            assert not hasattr(channel, attr), f"el canal no debería tener el atributo {attr!r}"

    def test_channel_only_has_transport_and_clock(self):
        channel = SlackNotificationChannel(transport=FakeSlackTransport())
        assert set(vars(channel).keys()) == {"_transport", "_clock"}

    def test_repr_does_not_contain_webhook(self):
        channel = SlackNotificationChannel(transport=FakeSlackTransport())
        assert "FAKE-WEBHOOK-VALUE" not in repr(channel)

    def test_str_does_not_contain_webhook(self):
        channel = SlackNotificationChannel(transport=FakeSlackTransport())
        assert "FAKE-WEBHOOK-VALUE" not in str(channel)


class TestSlackNotificationChannelDelivery:
    def test_successful_delivery_invokes_transport_once(self):
        transport = FakeSlackTransport()
        channel = SlackNotificationChannel(transport=transport, clock=FixedClock(_now()))
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        result = channel.deliver(message)
        assert result.success is True
        assert len(transport.calls) == 1

    def test_uses_injected_clock_for_delivered_at(self):
        fixed = datetime(2030, 7, 7, tzinfo=timezone.utc)
        channel = SlackNotificationChannel(transport=FakeSlackTransport(), clock=FixedClock(fixed))
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.delivered_at == fixed

    def test_does_not_modify_the_message(self):
        transport = FakeSlackTransport()
        channel = SlackNotificationChannel(transport=transport)
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        channel.deliver(message)
        assert message == NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)

    def test_transport_receives_only_text(self):
        transport = FakeSlackTransport()
        channel = SlackNotificationChannel(transport=transport)
        channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert list(transport.calls[0].keys()) == ["text"]
        assert transport.calls[0]["text"] == "T\n\nB"

    def test_transport_failure_returns_failed_result_without_raising(self):
        transport = FakeSlackTransport(fail_times=99)
        channel = SlackNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False

    def test_transport_failure_message_passes_through_unmodified(self):
        transport = FakeSlackTransport(fail_times=99, error_message="Slack webhook request failed (HTTP 400).")
        channel = SlackNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.error_message == "Slack webhook request failed (HTTP 400)."

    def test_deliver_never_retries_internally(self):
        transport = FakeSlackTransport(fail_times=1)
        channel = SlackNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False
        assert len(transport.calls) == 1


class TestSlackChannelIdentity:
    """Etapa 6.13 (§28, punto 21): la identidad persistente del canal es
    exactamente type(channel).__name__ == 'SlackNotificationChannel'."""

    def test_persisted_identity_is_the_class_name(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-sl", deduplication_key="k-sl")
        _seed_alert(repo, alert)
        transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=transport, clock=FixedClock(_now()))
        composite = CompositeNotificationChannel([slack_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message(alert_id="alert-sl"))
        state = repo.get_alert_channel_delivery("alert-sl", "SlackNotificationChannel")
        assert state is not None
        assert state.status == AlertStatus.DELIVERED


class TestSlackEndToEndWithoutInternet:
    """Punto 28: integración interna completa (repositorio real,
    DefaultInspectionNotificationTemplate real, SlackNotificationChannel
    con FakeSlackTransport -- nunca UrllibSlackTransport --,
    CompositeNotificationChannel, AlertDeliveryService)."""

    def test_full_pipeline_delivers_and_never_resends(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()

        alert = InspectionAlert(
            id="alert-slack-e2e", run_id="run-slack-e2e", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
            issue_code=None, severity=None, title="t", message="Inconsistencia detectada.",
            deduplication_key="dedup-slack-e2e", status=AlertStatus.PENDING, delivery_attempts=0,
            last_error=None, created_at=_now(),
        )
        _seed_alert(repo1, alert)

        transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=transport, clock=FixedClock(_now()))
        composite1 = CompositeNotificationChannel([slack_channel], repository=repo1, max_attempts=3, clock=FixedClock(_now()))
        service1 = AlertDeliveryService(
            repo1, composite1, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )

        result = service1.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(transport.calls) == 1
        assert "Inconsistencia detectada." in transport.calls[0]["text"]
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-slack-e2e").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-slack-e2e", "SlackNotificationChannel").status == AlertStatus.DELIVERED

        # Segundo procesamiento: no reenvía.
        service1.deliver_pending_alerts()
        assert len(transport.calls) == 1

        # "Reinicio": nueva instancia de repositorio + servicios sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([slack_channel], repository=repo2, max_attempts=3, clock=FixedClock(_now()))
        service2 = AlertDeliveryService(
            repo2, composite2, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )
        service2.deliver_pending_alerts()
        assert len(transport.calls) == 1  # Slack no se vuelve a invocar tras el reinicio.


class FakeEmailTransport:
    """Doble de EmailTransport (Etapa 6.14): nunca realiza ninguna
    conexión SMTP real. Solo recibe `subject`/`body`, igual que el
    contrato real de `send_message()`."""

    def __init__(self, fail_times: int = 0, error_message: str = "SMTP message delivery failed."):
        self.calls: list = []
        self._fail_times = fail_times
        self._error_message = error_message

    def send_message(self, *, subject, body):
        self.calls.append(dict(subject=subject, body=body))
        if len(self.calls) <= self._fail_times:
            raise EmailTransportError(self._error_message)


class TestEmailSubjectFormat:
    """Etapa 6.14 (§29): _format_email_subject() es pura, determinista,
    nunca incluye alert_id/metadata, y neutraliza CR/LF/tabs."""

    def test_includes_prefix_and_title(self):
        message = NotificationMessage(alert_id="a1", title="Titulo", body="Cuerpo", severity=None)
        subject = _format_email_subject(message)
        assert subject == "[Crypto AI] Titulo"

    def test_does_not_include_alert_id_or_metadata(self):
        message = NotificationMessage(
            alert_id="alert-secreto", title="T", body="B", severity=None,
            metadata={"run_id": "run-1", "alert_type": "NEW_ISSUE"},
        )
        subject = _format_email_subject(message)
        assert "alert-secreto" not in subject
        assert "run-1" not in subject
        assert "alert_type" not in subject

    def test_is_deterministic(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        assert _format_email_subject(message) == _format_email_subject(message)


class TestEmailHeaderInjection:
    """Etapa 6.14 (§29, punto 20): defensa en profundidad contra header
    injection en el asunto -- CR/LF/tabs se neutralizan aunque el
    NotificationMessage ya haya pasado por el Template."""

    def test_newline_in_title_neutralized(self):
        message = NotificationMessage(alert_id="a1", title="Hola\nMundo", body="B", severity=None)
        subject = _format_email_subject(message)
        assert "\n" not in subject
        assert "Hola" in subject and "Mundo" in subject

    def test_carriage_return_in_title_neutralized(self):
        message = NotificationMessage(alert_id="a1", title="Hola\r\nMundo", body="B", severity=None)
        subject = _format_email_subject(message)
        assert "\r" not in subject
        assert "\n" not in subject

    def test_bcc_header_injection_neutralized(self):
        message = NotificationMessage(
            alert_id="a1", title="Alerta\nBcc: victim@evil.com", body="B", severity=None,
        )
        subject = _format_email_subject(message)
        assert "\n" not in subject
        assert "Bcc:" in subject  # texto literal inofensivo, nunca una cabecera nueva

    def test_cc_header_injection_neutralized(self):
        message = NotificationMessage(
            alert_id="a1", title="Alerta\nCc: victim@evil.com", body="B", severity=None,
        )
        subject = _format_email_subject(message)
        assert "\n" not in subject

    def test_tabs_in_title_neutralized(self):
        message = NotificationMessage(alert_id="a1", title="Hola\tMundo", body="B", severity=None)
        subject = _format_email_subject(message)
        assert "\t" not in subject


class TestEmailSubjectLength:
    def test_short_subject_is_not_altered(self):
        message = NotificationMessage(alert_id="a1", title="Titulo corto", body="B", severity=None)
        assert _format_email_subject(message) == "[Crypto AI] Titulo corto"

    def test_subject_over_limit_is_truncated(self):
        message = NotificationMessage(alert_id="a1", title="x" * 300, body="B", severity=None)
        subject = _format_email_subject(message)
        assert len(subject) <= EMAIL_MAX_SUBJECT_LENGTH
        assert subject.endswith("…")

    def test_truncated_subject_never_exceeds_max_length(self):
        message = NotificationMessage(alert_id="a1", title="y" * 1000, body="B", severity=None)
        subject = _format_email_subject(message)
        assert len(subject) == EMAIL_MAX_SUBJECT_LENGTH


class TestEmailBodyFormat:
    def test_includes_title_and_body(self):
        message = NotificationMessage(alert_id="a1", title="Titulo", body="Cuerpo", severity=None)
        text = _format_email_body(message)
        assert "Titulo" in text
        assert "Cuerpo" in text

    def test_includes_severity_when_present(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        text = _format_email_body(message)
        assert "Severidad: CRITICAL" in text

    def test_omits_severity_line_when_none(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        text = _format_email_body(message)
        assert "Severidad" not in text

    def test_does_not_include_metadata_or_alert_id(self):
        message = NotificationMessage(
            alert_id="alert-secreto", title="T", body="B", severity=None,
            metadata={"run_id": "run-1", "alert_type": "NEW_ISSUE"},
        )
        text = _format_email_body(message)
        assert "alert-secreto" not in text
        assert "run-1" not in text

    def test_is_deterministic(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        assert _format_email_body(message) == _format_email_body(message)


class TestEmailFormatterPurity:
    """Etapa 6.14 (§29): _format_email_subject()/_format_email_body()
    dependen exclusivamente de `message` y constantes inmutables del
    módulo -- nunca de clock, entorno, locale, red ni estado global
    (mismo criterio que Telegram/Slack, §27.x/§28)."""

    def test_subject_signature_does_not_admit_a_clock(self):
        import inspect

        assert list(inspect.signature(_format_email_subject).parameters) == ["message"]

    def test_body_signature_does_not_admit_a_clock(self):
        import inspect

        assert list(inspect.signature(_format_email_body).parameters) == ["message"]

    def test_independent_of_environment_variables(self, monkeypatch):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        before_subject = _format_email_subject(message)
        before_body = _format_email_body(message)

        for var, value in (
            ("TZ", "America/Argentina/Buenos_Aires"), ("LANG", "es_AR.UTF-8"), ("LC_ALL", "es_AR.UTF-8"),
            ("EMAIL_SMTP_PASSWORD", "deberia-ser-ignorado"),
        ):
            monkeypatch.setenv(var, value)

        assert _format_email_subject(message) == before_subject
        assert _format_email_body(message) == before_body

    def test_does_not_mutate_the_message(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        before = repr(message)
        _format_email_subject(message)
        _format_email_body(message)
        after = repr(message)
        assert before == after

    def test_has_no_side_effects_source_inspection(self):
        import inspect

        source = inspect.getsource(_format_email_subject) + inspect.getsource(_format_email_body)
        forbidden_identifiers = (
            "logger.", "logging.", "print(", "open(", "socket.", "smtplib.", "ssl.",
            "self._repository", "repository.", "os.environ", "os.getenv",
        )
        for forbidden in forbidden_identifiers:
            assert forbidden not in source


class TestEmailBodyLength:
    def test_short_body_is_not_altered(self):
        message = NotificationMessage(alert_id="a1", title="T", body="cuerpo corto", severity=None)
        text = _format_email_body(message)
        assert text == "T\n\ncuerpo corto"

    def test_text_at_exact_limit_is_not_truncated(self):
        body = "x" * (EMAIL_MAX_BODY_LENGTH - len("T\n\n"))
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_email_body(message)
        assert len(text) == EMAIL_MAX_BODY_LENGTH
        assert "truncado" not in text

    def test_text_over_limit_is_truncated_with_mark(self):
        body = "x" * (EMAIL_MAX_BODY_LENGTH * 2)
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_email_body(message)
        assert len(text) <= EMAIL_MAX_BODY_LENGTH
        assert text.endswith("[Mensaje truncado]")

    def test_truncated_text_never_exceeds_max_length(self):
        body = "y" * (EMAIL_MAX_BODY_LENGTH + 1)
        message = NotificationMessage(alert_id="a1", title="T", body=body, severity=None)
        text = _format_email_body(message)
        assert len(text) == EMAIL_MAX_BODY_LENGTH


class TestEmailNotificationChannelConstructor:
    """Etapa 6.14 (§29): el constructor solo acepta transport/clock."""

    def test_only_accepts_transport_and_clock(self):
        import inspect

        params = list(inspect.signature(EmailNotificationChannel.__init__).parameters)
        assert params == ["self", "transport", "clock"]

    def test_host_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(host="smtp.example.com", transport=FakeEmailTransport())

    def test_port_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(port=587, transport=FakeEmailTransport())

    def test_username_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(username="u", transport=FakeEmailTransport())

    def test_password_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(password="p", transport=FakeEmailTransport())

    def test_sender_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(sender="a@example.com", transport=FakeEmailTransport())

    def test_recipient_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(recipient="b@example.com", transport=FakeEmailTransport())

    def test_timeout_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            EmailNotificationChannel(timeout_seconds=5.0, transport=FakeEmailTransport())

    def test_valid_configuration_constructs_successfully(self):
        assert EmailNotificationChannel(transport=FakeEmailTransport()) is not None


class TestEmailChannelHasNoCredentials:
    def test_channel_has_no_smtp_attributes(self):
        channel = EmailNotificationChannel(transport=FakeEmailTransport())
        forbidden_attrs = (
            "_host", "host", "_port", "port", "_username", "username", "_password", "password",
            "_sender", "sender", "_recipient", "recipient", "_timeout_seconds", "timeout_seconds", "_config", "config",
        )
        for attr in forbidden_attrs:
            assert not hasattr(channel, attr), f"el canal no debería tener el atributo {attr!r}"

    def test_channel_only_has_transport_and_clock(self):
        channel = EmailNotificationChannel(transport=FakeEmailTransport())
        assert set(vars(channel).keys()) == {"_transport", "_clock"}

    def test_repr_does_not_contain_password(self):
        channel = EmailNotificationChannel(transport=FakeEmailTransport())
        assert "MY-SUPER-SECRET" not in repr(channel)

    def test_str_does_not_contain_password(self):
        channel = EmailNotificationChannel(transport=FakeEmailTransport())
        assert "MY-SUPER-SECRET" not in str(channel)


class TestEmailNotificationChannelDelivery:
    def test_successful_delivery_invokes_transport_once(self):
        transport = FakeEmailTransport()
        channel = EmailNotificationChannel(transport=transport, clock=FixedClock(_now()))
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        result = channel.deliver(message)
        assert result.success is True
        assert len(transport.calls) == 1

    def test_uses_injected_clock_for_delivered_at(self):
        fixed = datetime(2030, 8, 8, tzinfo=timezone.utc)
        channel = EmailNotificationChannel(transport=FakeEmailTransport(), clock=FixedClock(fixed))
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.delivered_at == fixed

    def test_does_not_modify_the_message(self):
        transport = FakeEmailTransport()
        channel = EmailNotificationChannel(transport=transport)
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        channel.deliver(message)
        assert message == NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)

    def test_transport_receives_subject_and_body(self):
        transport = FakeEmailTransport()
        channel = EmailNotificationChannel(transport=transport)
        channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert set(transport.calls[0].keys()) == {"subject", "body"}
        assert transport.calls[0]["subject"] == "[Crypto AI] T"
        assert transport.calls[0]["body"] == "T\n\nB"

    def test_transport_failure_returns_failed_result_without_raising(self):
        transport = FakeEmailTransport(fail_times=99)
        channel = EmailNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False

    def test_result_is_never_terminal(self):
        transport = FakeEmailTransport(fail_times=99)
        channel = EmailNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.terminal is False

    def test_transport_failure_message_passes_through_unmodified(self):
        transport = FakeEmailTransport(fail_times=99, error_message="SMTP authentication failed.")
        channel = EmailNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.error_message == "SMTP authentication failed."

    def test_deliver_never_retries_internally(self):
        transport = FakeEmailTransport(fail_times=1)
        channel = EmailNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False
        assert len(transport.calls) == 1


class TestEmailChannelIdentity:
    """Etapa 6.14 (§29, punto 22): la identidad persistente del canal es
    exactamente type(channel).__name__ == 'EmailNotificationChannel'."""

    def test_persisted_identity_is_the_class_name(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-em", deduplication_key="k-em")
        _seed_alert(repo, alert)
        transport = FakeEmailTransport()
        email_channel = EmailNotificationChannel(transport=transport, clock=FixedClock(_now()))
        composite = CompositeNotificationChannel([email_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message(alert_id="alert-em"))
        state = repo.get_alert_channel_delivery("alert-em", "EmailNotificationChannel")
        assert state is not None
        assert state.status == AlertStatus.DELIVERED


class TestEmailEndToEndWithoutInternet:
    """Punto 34: integración interna completa (repositorio real,
    DefaultInspectionNotificationTemplate real, EmailNotificationChannel
    con FakeEmailTransport -- nunca SmtpEmailTransport --,
    CompositeNotificationChannel, AlertDeliveryService)."""

    def test_full_pipeline_delivers_and_never_resends(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()

        alert = InspectionAlert(
            id="alert-email-e2e", run_id="run-email-e2e", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
            issue_code=None, severity=None, title="t", message="Inconsistencia detectada.",
            deduplication_key="dedup-email-e2e", status=AlertStatus.PENDING, delivery_attempts=0,
            last_error=None, created_at=_now(),
        )
        _seed_alert(repo1, alert)

        transport = FakeEmailTransport()
        email_channel = EmailNotificationChannel(transport=transport, clock=FixedClock(_now()))
        composite1 = CompositeNotificationChannel([email_channel], repository=repo1, max_attempts=3, clock=FixedClock(_now()))
        service1 = AlertDeliveryService(
            repo1, composite1, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )

        result = service1.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(transport.calls) == 1
        assert "Inconsistencia detectada." in transport.calls[0]["body"]
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-email-e2e").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-email-e2e", "EmailNotificationChannel").status == AlertStatus.DELIVERED

        # Segundo procesamiento: no reenvía.
        service1.deliver_pending_alerts()
        assert len(transport.calls) == 1

        # "Reinicio": nueva instancia de repositorio + servicios sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([email_channel], repository=repo2, max_attempts=3, clock=FixedClock(_now()))
        service2 = AlertDeliveryService(
            repo2, composite2, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )
        service2.deliver_pending_alerts()
        assert len(transport.calls) == 1  # Email no se vuelve a invocar tras el reinicio.


class FakeWebhookTransport:
    """Doble de WebhookTransport (Etapa 6.15): nunca realiza ninguna
    conexión real. Solo recibe `payload`, igual que el contrato real de
    `send_payload()`."""

    def __init__(self, fail_times: int = 0, error_message: str = "Webhook request failed (HTTP 500)."):
        self.calls: list = []
        self._fail_times = fail_times
        self._error_message = error_message

    def send_payload(self, *, payload):
        self.calls.append(dict(payload=payload))
        if len(self.calls) <= self._fail_times:
            raise WebhookTransportError(self._error_message)


class TestWebhookPayload:
    """Etapa 6.15 (§30): _build_webhook_payload() es puro, determinista,
    con estructura fija (version/event_type/alert.id/title/body/severity),
    sin metadata arbitraria ni credenciales."""

    def test_exact_structure(self):
        message = NotificationMessage(alert_id="a1", title="Titulo", body="Cuerpo", severity=IssueSeverity.CRITICAL)
        payload = _build_webhook_payload(message)
        assert payload == {
            "version": "1",
            "event_type": "paper_trading.inspection_alert",
            "alert": {"id": "a1", "title": "Titulo", "body": "Cuerpo", "severity": "CRITICAL"},
        }

    def test_severity_absent_is_null(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        payload = _build_webhook_payload(message)
        assert payload["alert"]["severity"] is None

    def test_alert_id_matches_message(self):
        message = NotificationMessage(alert_id="alert-xyz", title="T", body="B", severity=None)
        payload = _build_webhook_payload(message)
        assert payload["alert"]["id"] == "alert-xyz"

    def test_no_arbitrary_metadata(self):
        message = NotificationMessage(
            alert_id="a1", title="T", body="B", severity=None,
            metadata={"run_id": "run-1", "alert_type": "NEW_ISSUE"},
        )
        payload = _build_webhook_payload(message)
        assert "metadata" not in payload
        assert "run_id" not in json.dumps(payload)
        assert "alert_type" not in json.dumps(payload)

    def test_no_credentials(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        payload = _build_webhook_payload(message)
        serialized = json.dumps(payload)
        for forbidden in ("authorization", "secret", "token", "password"):
            assert forbidden not in serialized.lower()

    def test_is_deterministic(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        assert _build_webhook_payload(message) == _build_webhook_payload(message)

    def test_does_not_mutate_the_message(self):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.INFO)
        before = repr(message)
        _build_webhook_payload(message)
        assert repr(message) == before

    def test_independent_of_environment_variables(self, monkeypatch):
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL)
        before = _build_webhook_payload(message)
        for var, value in (
            ("TZ", "America/Argentina/Buenos_Aires"),
            ("WEBHOOK_ENDPOINT_URL", "https://deberia-ser-ignorado.example.com/x"),
            ("WEBHOOK_AUTHORIZATION_SECRET", "deberia-ser-ignorado"),
        ):
            monkeypatch.setenv(var, value)
        after = _build_webhook_payload(message)
        assert before == after

    def test_unicode_body_roundtrips(self):
        message = NotificationMessage(alert_id="a1", title="T", body="acentuación: áéíóú ñ", severity=None)
        payload = _build_webhook_payload(message)
        assert payload["alert"]["body"] == "acentuación: áéíóú ñ"

    def test_empty_body_is_allowed(self):
        message = NotificationMessage(alert_id="a1", title="T", body="", severity=None)
        payload = _build_webhook_payload(message)
        assert payload["alert"]["body"] == ""

    def test_huge_body_is_truncated_within_size_limit(self):
        message = NotificationMessage(alert_id="a1", title="T", body="x" * 500000, severity=None)
        payload = _build_webhook_payload(message)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        assert len(encoded) <= WEBHOOK_MAX_PAYLOAD_BYTES
        assert payload["alert"]["body"].endswith("[Mensaje truncado]")

    def test_only_body_is_truncated_never_title_or_id(self):
        message = NotificationMessage(alert_id="alert-preserved", title="Titulo preservado", body="x" * 500000, severity=None)
        payload = _build_webhook_payload(message)
        assert payload["alert"]["id"] == "alert-preserved"
        assert payload["alert"]["title"] == "Titulo preservado"

    def test_short_body_is_never_truncated(self):
        message = NotificationMessage(alert_id="a1", title="T", body="cuerpo corto", severity=None)
        payload = _build_webhook_payload(message)
        assert payload["alert"]["body"] == "cuerpo corto"

    def test_oversized_id_and_title_raise_controlled_error(self):
        """Si incluso con el cuerpo vacío el payload seguiría sin entrar
        en el límite (por ejemplo, un alert_id/title desmedido), se
        lanza WebhookTransportError antes de intentar ninguna conexión."""
        message = NotificationMessage(alert_id="i" * 100000, title="t" * 100000, body="x", severity=None)
        with pytest.raises(WebhookTransportError):
            _build_webhook_payload(message)


class TestWebhookNotificationChannelConstructor:
    """Etapa 6.15 (§30): el constructor solo acepta transport/clock."""

    def test_only_accepts_transport_and_clock(self):
        import inspect

        params = list(inspect.signature(WebhookNotificationChannel.__init__).parameters)
        assert params == ["self", "transport", "clock"]

    def test_endpoint_url_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            WebhookNotificationChannel(endpoint_url="https://example.com/hook", transport=FakeWebhookTransport())

    def test_authorization_secret_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            WebhookNotificationChannel(authorization_secret="s", transport=FakeWebhookTransport())

    def test_timeout_keyword_does_not_exist(self):
        with pytest.raises(TypeError):
            WebhookNotificationChannel(timeout_seconds=5.0, transport=FakeWebhookTransport())

    def test_valid_configuration_constructs_successfully(self):
        assert WebhookNotificationChannel(transport=FakeWebhookTransport()) is not None


class TestWebhookChannelHasNoCredentials:
    def test_channel_has_no_endpoint_or_secret_attributes(self):
        channel = WebhookNotificationChannel(transport=FakeWebhookTransport())
        forbidden_attrs = (
            "_endpoint_url", "endpoint_url", "_authorization_secret", "authorization_secret",
            "_timeout_seconds", "timeout_seconds", "_config", "config",
        )
        for attr in forbidden_attrs:
            assert not hasattr(channel, attr), f"el canal no debería tener el atributo {attr!r}"

    def test_channel_only_has_transport_and_clock(self):
        channel = WebhookNotificationChannel(transport=FakeWebhookTransport())
        assert set(vars(channel).keys()) == {"_transport", "_clock"}

    def test_repr_does_not_contain_secret(self):
        channel = WebhookNotificationChannel(transport=FakeWebhookTransport())
        assert "MY-SUPER-SECRET" not in repr(channel)

    def test_str_does_not_contain_secret(self):
        channel = WebhookNotificationChannel(transport=FakeWebhookTransport())
        assert "MY-SUPER-SECRET" not in str(channel)


class TestWebhookNotificationChannelDelivery:
    def test_successful_delivery_invokes_transport_once(self):
        transport = FakeWebhookTransport()
        channel = WebhookNotificationChannel(transport=transport, clock=FixedClock(_now()))
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=None)
        result = channel.deliver(message)
        assert result.success is True
        assert len(transport.calls) == 1

    def test_uses_injected_clock_for_delivered_at(self):
        fixed = datetime(2030, 9, 9, tzinfo=timezone.utc)
        channel = WebhookNotificationChannel(transport=FakeWebhookTransport(), clock=FixedClock(fixed))
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.delivered_at == fixed

    def test_does_not_modify_the_message(self):
        transport = FakeWebhookTransport()
        channel = WebhookNotificationChannel(transport=transport)
        message = NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)
        channel.deliver(message)
        assert message == NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.WARNING)

    def test_transport_receives_the_built_payload(self):
        transport = FakeWebhookTransport()
        channel = WebhookNotificationChannel(transport=transport)
        channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=IssueSeverity.CRITICAL))
        assert list(transport.calls[0].keys()) == ["payload"]
        assert transport.calls[0]["payload"] == {
            "version": "1", "event_type": "paper_trading.inspection_alert",
            "alert": {"id": "a1", "title": "T", "body": "B", "severity": "CRITICAL"},
        }

    def test_transport_failure_returns_failed_result_without_raising(self):
        transport = FakeWebhookTransport(fail_times=99)
        channel = WebhookNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False

    def test_result_is_never_terminal(self):
        transport = FakeWebhookTransport(fail_times=99)
        channel = WebhookNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.terminal is False

    def test_transport_failure_message_passes_through_unmodified(self):
        transport = FakeWebhookTransport(fail_times=99, error_message="Webhook request failed (HTTP 400).")
        channel = WebhookNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.error_message == "Webhook request failed (HTTP 400)."

    def test_deliver_never_retries_internally(self):
        transport = FakeWebhookTransport(fail_times=1)
        channel = WebhookNotificationChannel(transport=transport)
        result = channel.deliver(NotificationMessage(alert_id="a1", title="T", body="B", severity=None))
        assert result.success is False
        assert len(transport.calls) == 1


class TestWebhookChannelIdentity:
    """Etapa 6.15 (§30, punto 26): la identidad persistente del canal es
    exactamente type(channel).__name__ == 'WebhookNotificationChannel'."""

    def test_persisted_identity_is_the_class_name(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-wh", deduplication_key="k-wh")
        _seed_alert(repo, alert)
        transport = FakeWebhookTransport()
        webhook_channel = WebhookNotificationChannel(transport=transport, clock=FixedClock(_now()))
        composite = CompositeNotificationChannel([webhook_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message(alert_id="alert-wh"))
        state = repo.get_alert_channel_delivery("alert-wh", "WebhookNotificationChannel")
        assert state is not None
        assert state.status == AlertStatus.DELIVERED


class TestWebhookEndToEndWithoutInternet:
    """Etapa 6.15 (§30): integración interna completa (repositorio real,
    DefaultInspectionNotificationTemplate real, WebhookNotificationChannel
    con FakeWebhookTransport -- nunca UrllibWebhookTransport --,
    CompositeNotificationChannel, AlertDeliveryService)."""

    def test_full_pipeline_delivers_and_never_resends(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()

        alert = InspectionAlert(
            id="alert-webhook-e2e", run_id="run-webhook-e2e", alert_type=AlertType.NEW_ISSUE, issue_identity=None,
            issue_code=None, severity=None, title="t", message="Inconsistencia detectada.",
            deduplication_key="dedup-webhook-e2e", status=AlertStatus.PENDING, delivery_attempts=0,
            last_error=None, created_at=_now(),
        )
        _seed_alert(repo1, alert)

        transport = FakeWebhookTransport()
        webhook_channel = WebhookNotificationChannel(transport=transport, clock=FixedClock(_now()))
        composite1 = CompositeNotificationChannel([webhook_channel], repository=repo1, max_attempts=3, clock=FixedClock(_now()))
        service1 = AlertDeliveryService(
            repo1, composite1, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )

        result = service1.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(transport.calls) == 1
        assert "Inconsistencia detectada." in transport.calls[0]["payload"]["alert"]["body"]
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-webhook-e2e").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-webhook-e2e", "WebhookNotificationChannel").status == AlertStatus.DELIVERED

        # Segundo procesamiento: no reenvía.
        service1.deliver_pending_alerts()
        assert len(transport.calls) == 1

        # "Reinicio": nueva instancia de repositorio + servicios sobre el mismo archivo.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel([webhook_channel], repository=repo2, max_attempts=3, clock=FixedClock(_now()))
        service2 = AlertDeliveryService(
            repo2, composite2, max_attempts=3, clock=FixedClock(_now()),
            template=DefaultInspectionNotificationTemplate(),
        )
        service2.deliver_pending_alerts()
        assert len(transport.calls) == 1  # Webhook no se vuelve a invocar tras el reinicio.


class TestMultiChannelIntegration:
    """Punto 29 (6.13)/35 (6.14): Logging + Telegram (fake) + Slack
    (fake) + Email (fake) juntos en el mismo CompositeNotificationChannel."""

    def test_all_three_channels_succeed(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-multi", deduplication_key="dedup-multi")
        _seed_alert(repo, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=telegram_transport, clock=FixedClock(_now()))
        slack_transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=slack_transport, clock=FixedClock(_now()))

        composite = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        service = AlertDeliveryService(repo, composite, max_attempts=3, clock=FixedClock(_now()))
        result = service.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert repo.get_inspection_alert_by_deduplication_key("dedup-multi").status == AlertStatus.DELIVERED
        for channel_name in ("LoggingNotificationChannel", "TelegramNotificationChannel", "SlackNotificationChannel"):
            state = repo.get_alert_channel_delivery("alert-multi", channel_name)
            assert state is not None
            assert state.status == AlertStatus.DELIVERED

    def test_all_four_channels_succeed(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-multi4", deduplication_key="dedup-multi4")
        _seed_alert(repo, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=telegram_transport, clock=FixedClock(_now()))
        slack_transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=slack_transport, clock=FixedClock(_now()))
        email_transport = FakeEmailTransport()
        email_channel = EmailNotificationChannel(transport=email_transport, clock=FixedClock(_now()))

        composite = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel, email_channel],
            repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        service = AlertDeliveryService(repo, composite, max_attempts=3, clock=FixedClock(_now()))
        result = service.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 1
        assert repo.get_inspection_alert_by_deduplication_key("dedup-multi4").status == AlertStatus.DELIVERED
        for channel_name in (
            "LoggingNotificationChannel", "TelegramNotificationChannel",
            "SlackNotificationChannel", "EmailNotificationChannel",
        ):
            state = repo.get_alert_channel_delivery("alert-multi4", channel_name)
            assert state is not None
            assert state.status == AlertStatus.DELIVERED

    def test_all_five_channels_succeed(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-multi5", deduplication_key="dedup-multi5")
        _seed_alert(repo, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=telegram_transport, clock=FixedClock(_now()))
        slack_transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=slack_transport, clock=FixedClock(_now()))
        email_transport = FakeEmailTransport()
        email_channel = EmailNotificationChannel(transport=email_transport, clock=FixedClock(_now()))
        webhook_transport = FakeWebhookTransport()
        webhook_channel = WebhookNotificationChannel(transport=webhook_transport, clock=FixedClock(_now()))

        composite = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel, email_channel, webhook_channel],
            repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        service = AlertDeliveryService(repo, composite, max_attempts=3, clock=FixedClock(_now()))
        result = service.deliver_pending_alerts()

        assert result.delivered_count == 1
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 1
        assert len(webhook_transport.calls) == 1
        assert repo.get_inspection_alert_by_deduplication_key("dedup-multi5").status == AlertStatus.DELIVERED
        for channel_name in (
            "LoggingNotificationChannel", "TelegramNotificationChannel",
            "SlackNotificationChannel", "EmailNotificationChannel", "WebhookNotificationChannel",
        ):
            state = repo.get_alert_channel_delivery("alert-multi5", channel_name)
            assert state is not None
            assert state.status == AlertStatus.DELIVERED

    def test_webhook_fails_others_do_not_repeat_then_webhook_succeeds(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        alert = _alert(id="alert-multi-webhook", deduplication_key="dedup-multi-webhook")
        _seed_alert(repo1, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=telegram_transport, clock=FixedClock(_now()))
        slack_transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=slack_transport, clock=FixedClock(_now()))
        email_transport = FakeEmailTransport()
        email_channel = EmailNotificationChannel(transport=email_transport, clock=FixedClock(_now()))
        webhook_transport = FakeWebhookTransport(fail_times=1)
        webhook_channel = WebhookNotificationChannel(transport=webhook_transport, clock=FixedClock(_now()))

        composite1 = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel, email_channel, webhook_channel],
            repository=repo1, max_attempts=3, clock=FixedClock(_now()),
        )
        service1 = AlertDeliveryService(repo1, composite1, max_attempts=3, clock=FixedClock(_now()))

        service1.deliver_pending_alerts()
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 1
        assert len(webhook_transport.calls) == 1
        assert repo1.get_alert_channel_delivery("alert-multi-webhook", "LoggingNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-webhook", "TelegramNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-webhook", "SlackNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-webhook", "EmailNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-webhook", "WebhookNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-multi-webhook").status == AlertStatus.PENDING

        service1.deliver_pending_alerts()
        assert len(telegram_transport.calls) == 1  # no se repiten
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 1
        assert len(webhook_transport.calls) == 2  # solo Webhook se reintenta
        assert repo1.get_alert_channel_delivery("alert-multi-webhook", "WebhookNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-multi-webhook").status == AlertStatus.DELIVERED

        # "Reinicio": ningún canal ya DELIVERED se vuelve a invocar; solo pendientes se procesan.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel, email_channel, webhook_channel],
            repository=repo2, max_attempts=3, clock=FixedClock(_now()),
        )
        service2 = AlertDeliveryService(repo2, composite2, max_attempts=3, clock=FixedClock(_now()))
        result2 = service2.deliver_pending_alerts()
        assert result2.delivered_count == 0
        assert result2.failed_count == 0
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 1
        assert len(webhook_transport.calls) == 2

    def test_email_fails_others_do_not_repeat_then_email_succeeds(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        alert = _alert(id="alert-multi-email", deduplication_key="dedup-multi-email")
        _seed_alert(repo1, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=telegram_transport, clock=FixedClock(_now()))
        slack_transport = FakeSlackTransport()
        slack_channel = SlackNotificationChannel(transport=slack_transport, clock=FixedClock(_now()))
        email_transport = FakeEmailTransport(fail_times=1)
        email_channel = EmailNotificationChannel(transport=email_transport, clock=FixedClock(_now()))

        composite1 = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel, email_channel],
            repository=repo1, max_attempts=3, clock=FixedClock(_now()),
        )
        service1 = AlertDeliveryService(repo1, composite1, max_attempts=3, clock=FixedClock(_now()))

        service1.deliver_pending_alerts()
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 1
        assert repo1.get_alert_channel_delivery("alert-multi-email", "LoggingNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-email", "TelegramNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-email", "SlackNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi-email", "EmailNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-multi-email").status == AlertStatus.PENDING

        service1.deliver_pending_alerts()
        assert len(telegram_transport.calls) == 1  # no se repiten
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 2  # solo Email se reintenta
        assert repo1.get_alert_channel_delivery("alert-multi-email", "EmailNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-multi-email").status == AlertStatus.DELIVERED

        # "Reinicio": ningún canal ya DELIVERED se vuelve a invocar; solo pendientes se procesan.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel(
            [logging_channel, telegram_channel, slack_channel, email_channel],
            repository=repo2, max_attempts=3, clock=FixedClock(_now()),
        )
        service2 = AlertDeliveryService(repo2, composite2, max_attempts=3, clock=FixedClock(_now()))
        result2 = service2.deliver_pending_alerts()
        assert result2.delivered_count == 0
        assert result2.failed_count == 0
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert len(email_transport.calls) == 2

    def test_slack_fails_others_do_not_repeat_then_slack_succeeds(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        alert = _alert(id="alert-multi2", deduplication_key="dedup-multi2")
        _seed_alert(repo1, alert)

        telegram_transport = FakeTelegramTransport()
        telegram_channel = TelegramNotificationChannel(transport=telegram_transport, clock=FixedClock(_now()))
        slack_transport = FakeSlackTransport(fail_times=1)
        slack_channel = SlackNotificationChannel(transport=slack_transport, clock=FixedClock(_now()))

        composite1 = CompositeNotificationChannel(
            [telegram_channel, slack_channel], repository=repo1, max_attempts=3, clock=FixedClock(_now()),
        )
        service1 = AlertDeliveryService(repo1, composite1, max_attempts=3, clock=FixedClock(_now()))

        service1.deliver_pending_alerts()
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 1
        assert repo1.get_alert_channel_delivery("alert-multi2", "TelegramNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-multi2", "SlackNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-multi2").status == AlertStatus.PENDING

        service1.deliver_pending_alerts()
        assert len(telegram_transport.calls) == 1  # Telegram no se repite
        assert len(slack_transport.calls) == 2  # solo Slack se reintenta
        assert repo1.get_alert_channel_delivery("alert-multi2", "SlackNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_inspection_alert_by_deduplication_key("dedup-multi2").status == AlertStatus.DELIVERED

        # "Reinicio": ningún canal ya DELIVERED se vuelve a invocar.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel(
            [telegram_channel, slack_channel], repository=repo2, max_attempts=3, clock=FixedClock(_now()),
        )
        service2 = AlertDeliveryService(repo2, composite2, max_attempts=3, clock=FixedClock(_now()))
        result2 = service2.deliver_pending_alerts()
        assert result2.delivered_count == 0
        assert result2.failed_count == 0
        assert len(telegram_transport.calls) == 1
        assert len(slack_transport.calls) == 2
