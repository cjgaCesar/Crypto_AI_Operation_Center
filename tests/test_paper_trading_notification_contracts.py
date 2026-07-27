"""
Pruebas contractuales transversales del subsistema de notificaciones
(Etapa 6.16, §31): confirman que los cinco canales (Logging/Telegram/
Slack/Email/Webhook) funcionan como un único sistema coherente,
respetando el mismo contrato (`deliver(message) -> AlertDeliveryResult`)
sin importar cuál transporte concreto usen por debajo.

Este archivo NO duplica las suites específicas de cada canal/transporte
(test_paper_trading_notification_channels.py,
test_paper_trading_{telegram,slack,email,webhook}_transport.py,
test_paper_trading_composition.py): solo cubre aserciones que aplican
a los cinco canales a la vez, o escenarios de sistema completo
(idempotencia/reintentos/fallo simultáneo/observabilidad) que no tienen
un hogar natural en un archivo por-canal.

Ningún canal nuevo se agrega en esta etapa; ninguna conexión real
ocurre en ninguna prueba (todos los transportes externos se reemplazan
por dobles de prueba)."""

import inspect
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus, AlertType, InspectionAlert
from src.paper_trading.email_transport import EmailTransportError
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.notification_channels import (
    MAX_DELIVERY_ERROR_LENGTH,
    CompositeNotificationChannel, EmailNotificationChannel, InspectionNotificationChannel,
    LoggingNotificationChannel, NullNotificationChannel, SlackNotificationChannel,
    TelegramNotificationChannel, WebhookNotificationChannel,
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


def _seed_alert(repo, alert) -> None:
    run = ScheduledInspectionRun(
        id=alert.run_id, started_at=_now(), completed_at=_now(), success=True, report=None,
        previous_run_id=None, new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0,
        changed_issue_count=0, alert_count=1,
    )
    repo.save_inspection_run_transaction(run, [alert])


def _message(**overrides) -> NotificationMessage:
    defaults = dict(alert_id="alert-1", title="t", body="m", severity=None, metadata={})
    defaults.update(overrides)
    return NotificationMessage(**defaults)


# --------------------------------------------------------------------------
# Fakes de transporte -- cada uno replica exactamente el contrato real de
# su Protocol (send_message/send_payload), sin ninguna conexión real, y
# puede configurarse para fallar N veces o lanzar una excepción arbitraria.
# --------------------------------------------------------------------------

class FakeTelegramTransport:
    def __init__(self, fail_times: int = 0, raises: Exception = None,
                 error_message: str = "Telegram API returned an unsuccessful response."):
        self.calls: list = []
        self._fail_times = fail_times
        self._raises = raises
        self._error_message = error_message

    def send_message(self, *, text):
        self.calls.append(dict(text=text))
        if self._raises is not None and len(self.calls) <= self._fail_times:
            raise self._raises
        if len(self.calls) <= self._fail_times:
            raise TelegramTransportError(self._error_message)


class FakeSlackTransport:
    def __init__(self, fail_times: int = 0, raises: Exception = None,
                 error_message: str = "Slack webhook returned an unsuccessful response."):
        self.calls: list = []
        self._fail_times = fail_times
        self._raises = raises
        self._error_message = error_message

    def send_message(self, *, text):
        self.calls.append(dict(text=text))
        if self._raises is not None and len(self.calls) <= self._fail_times:
            raise self._raises
        if len(self.calls) <= self._fail_times:
            raise SlackTransportError(self._error_message)


class FakeEmailTransport:
    def __init__(self, fail_times: int = 0, raises: Exception = None,
                 error_message: str = "SMTP message delivery failed."):
        self.calls: list = []
        self._fail_times = fail_times
        self._raises = raises
        self._error_message = error_message

    def send_message(self, *, subject, body):
        self.calls.append(dict(subject=subject, body=body))
        if self._raises is not None and len(self.calls) <= self._fail_times:
            raise self._raises
        if len(self.calls) <= self._fail_times:
            raise EmailTransportError(self._error_message)


class FakeWebhookTransport:
    def __init__(self, fail_times: int = 0, raises: Exception = None,
                 error_message: str = "Webhook request failed (HTTP 500)."):
        self.calls: list = []
        self._fail_times = fail_times
        self._raises = raises
        self._error_message = error_message

    def send_payload(self, *, payload):
        self.calls.append(dict(payload=payload))
        if self._raises is not None and len(self.calls) <= self._fail_times:
            raise self._raises
        if len(self.calls) <= self._fail_times:
            raise WebhookTransportError(self._error_message)


def _all_real_channels_with_fakes(fail_times: int = 0, clock=None):
    """Construye los 5 canales reales (más Logging/Null, que no tienen
    transporte externo) con dobles de transporte, listos para pruebas
    parametrizadas. Devuelve una lista de (channel_name, channel, fake)."""
    clock = clock or FixedClock(_now())
    telegram_fake = FakeTelegramTransport(fail_times=fail_times)
    slack_fake = FakeSlackTransport(fail_times=fail_times)
    email_fake = FakeEmailTransport(fail_times=fail_times)
    webhook_fake = FakeWebhookTransport(fail_times=fail_times)
    return [
        ("TelegramNotificationChannel", TelegramNotificationChannel(transport=telegram_fake, clock=clock), telegram_fake),
        ("SlackNotificationChannel", SlackNotificationChannel(transport=slack_fake, clock=clock), slack_fake),
        ("EmailNotificationChannel", EmailNotificationChannel(transport=email_fake, clock=clock), email_fake),
        ("WebhookNotificationChannel", WebhookNotificationChannel(transport=webhook_fake, clock=clock), webhook_fake),
    ]


_EXTERNAL_CHANNEL_FACTORIES = [
    ("TelegramNotificationChannel", lambda clock: TelegramNotificationChannel(transport=FakeTelegramTransport(), clock=clock)),
    ("SlackNotificationChannel", lambda clock: SlackNotificationChannel(transport=FakeSlackTransport(), clock=clock)),
    ("EmailNotificationChannel", lambda clock: EmailNotificationChannel(transport=FakeEmailTransport(), clock=clock)),
    ("WebhookNotificationChannel", lambda clock: WebhookNotificationChannel(transport=FakeWebhookTransport(), clock=clock)),
]

_ALL_FIVE_CHANNEL_FACTORIES = [
    ("LoggingNotificationChannel", lambda clock: LoggingNotificationChannel(clock=clock)),
] + _EXTERNAL_CHANNEL_FACTORIES

_CHANNEL_CLASSES = [
    LoggingNotificationChannel, TelegramNotificationChannel, SlackNotificationChannel,
    EmailNotificationChannel, WebhookNotificationChannel, NullNotificationChannel,
    CompositeNotificationChannel,
]


# --------------------------------------------------------------------------
# §31, punto 4: firma común deliver(message) -> AlertDeliveryResult
# --------------------------------------------------------------------------

class TestDeliverSignatureContract:
    @pytest.mark.parametrize("channel_class", _CHANNEL_CLASSES)
    def test_deliver_method_exists_with_message_parameter(self, channel_class):
        params = list(inspect.signature(channel_class.deliver).parameters)
        assert params == ["self", "message"]

    @pytest.mark.parametrize("channel_class", _CHANNEL_CLASSES)
    def test_deliver_return_annotation_is_alert_delivery_result(self, channel_class):
        signature = inspect.signature(channel_class.deliver)
        assert signature.return_annotation in (AlertDeliveryResult, "AlertDeliveryResult")


class TestClockUsageContract:
    @pytest.mark.parametrize("name,factory", _ALL_FIVE_CHANNEL_FACTORIES)
    def test_successful_delivery_uses_injected_clock(self, name, factory):
        fixed = datetime(2031, 2, 2, tzinfo=timezone.utc)
        channel = factory(FixedClock(fixed))
        result = channel.deliver(_message())
        assert result.delivered_at == fixed


class TestSuccessResultContract:
    @pytest.mark.parametrize("name,factory", _ALL_FIVE_CHANNEL_FACTORIES)
    def test_success_result_shape(self, name, factory):
        channel = factory(FixedClock(_now()))
        result = channel.deliver(_message())
        assert result.success is True
        assert result.error_message is None
        assert result.terminal is False
        assert result.delivered_at == _now()


class TestTransientFailureResultContract:
    @pytest.mark.parametrize("name,transport_factory,channel_factory", [
        ("TelegramNotificationChannel", lambda: FakeTelegramTransport(fail_times=99),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock)),
        ("SlackNotificationChannel", lambda: FakeSlackTransport(fail_times=99),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock)),
        ("EmailNotificationChannel", lambda: FakeEmailTransport(fail_times=99),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock)),
        ("WebhookNotificationChannel", lambda: FakeWebhookTransport(fail_times=99),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock)),
    ])
    def test_transient_failure_result_shape(self, name, transport_factory, channel_factory):
        transport = transport_factory()
        channel = channel_factory(transport, FixedClock(_now()))
        result = channel.deliver(_message())
        assert result.success is False
        assert isinstance(result.error_message, str) and result.error_message
        assert result.terminal is False


class TestNoMutationContract:
    @pytest.mark.parametrize("name,factory", _ALL_FIVE_CHANNEL_FACTORIES)
    def test_message_unchanged_after_successful_delivery(self, name, factory):
        channel = factory(FixedClock(_now()))
        message = _message(severity=IssueSeverity.WARNING)
        before = repr(message)
        channel.deliver(message)
        assert repr(message) == before

    @pytest.mark.parametrize("name,transport_factory,channel_factory", [
        ("TelegramNotificationChannel", lambda: FakeTelegramTransport(fail_times=99),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock)),
        ("SlackNotificationChannel", lambda: FakeSlackTransport(fail_times=99),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock)),
        ("EmailNotificationChannel", lambda: FakeEmailTransport(fail_times=99),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock)),
        ("WebhookNotificationChannel", lambda: FakeWebhookTransport(fail_times=99),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock)),
    ])
    def test_message_unchanged_after_failed_delivery(self, name, transport_factory, channel_factory):
        channel = channel_factory(transport_factory(), FixedClock(_now()))
        message = _message(severity=IssueSeverity.CRITICAL)
        before = repr(message)
        channel.deliver(message)
        assert repr(message) == before


class TestNoInternalRetriesContract:
    @pytest.mark.parametrize("name,transport_factory,channel_factory", [
        ("TelegramNotificationChannel", lambda: FakeTelegramTransport(fail_times=1),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock)),
        ("SlackNotificationChannel", lambda: FakeSlackTransport(fail_times=1),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock)),
        ("EmailNotificationChannel", lambda: FakeEmailTransport(fail_times=1),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock)),
        ("WebhookNotificationChannel", lambda: FakeWebhookTransport(fail_times=1),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock)),
    ])
    def test_exactly_one_transport_invocation_per_deliver_call(self, name, transport_factory, channel_factory):
        transport = transport_factory()
        channel = channel_factory(transport, FixedClock(_now()))
        result = channel.deliver(_message())
        assert result.success is False
        assert len(transport.calls) == 1


_SENSITIVE_EXCEPTION_TEXT = (
    "token=SECRET-ABC123 "
    "password=hunter2 "
    "url=https://secret.example/hook "
    "Authorization=Bearer TOP-SECRET"
)


class TestUnexpectedFailureSanitization:
    """§31.x (Etapa 6.16.1): una excepción inesperada (RuntimeError,
    ValueError, TypeError, KeyError, Exception genérica -- nunca uno de
    los cuatro `*TransportError` controlados) jamás expone `str(exc)`/
    `repr(exc)`/`exc.args`/traceback -- se reemplaza siempre por
    `"Unexpected failure in <ChannelClassName>."`, determinista y sin
    ningún dato del origen real."""

    @pytest.mark.parametrize("channel_name,exception_cls,transport_factory,channel_factory", [
        ("TelegramNotificationChannel", RuntimeError,
         lambda exc: FakeTelegramTransport(fail_times=1, raises=exc),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock)),
        ("SlackNotificationChannel", ValueError,
         lambda exc: FakeSlackTransport(fail_times=1, raises=exc),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock)),
        ("EmailNotificationChannel", TypeError,
         lambda exc: FakeEmailTransport(fail_times=1, raises=exc),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock)),
        ("WebhookNotificationChannel", KeyError,
         lambda exc: FakeWebhookTransport(fail_times=1, raises=exc),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock)),
    ])
    def test_unexpected_exception_never_propagates_and_is_fully_sanitized(
        self, channel_name, exception_cls, transport_factory, channel_factory,
    ):
        exc = exception_cls(_SENSITIVE_EXCEPTION_TEXT)
        transport = transport_factory(exc)
        channel = channel_factory(transport, FixedClock(_now()))
        result = channel.deliver(_message())  # no debe lanzar

        assert result.success is False
        assert result.terminal is False
        assert result.error_message
        assert len(result.error_message) <= MAX_DELIVERY_ERROR_LENGTH

        assert "SECRET-ABC123" not in result.error_message
        assert "hunter2" not in result.error_message
        assert "secret.example" not in result.error_message
        assert "TOP-SECRET" not in result.error_message
        assert "Authorization" not in result.error_message

        assert result.error_message == f"Unexpected failure in {channel_name}."

    def test_logging_channel_failure_is_fully_sanitized(self, monkeypatch):
        import src.paper_trading.notification_channels as module

        channel = LoggingNotificationChannel(clock=FixedClock(_now()))

        def _raise(*args, **kwargs):
            raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

        monkeypatch.setattr(module.logger, "info", _raise)
        result = channel.deliver(_message())  # no debe lanzar

        assert result.success is False
        assert result.terminal is False
        assert result.error_message
        assert len(result.error_message) <= MAX_DELIVERY_ERROR_LENGTH

        assert "SECRET-ABC123" not in result.error_message
        assert "hunter2" not in result.error_message
        assert "secret.example" not in result.error_message
        assert "TOP-SECRET" not in result.error_message
        assert "Authorization" not in result.error_message

        assert result.error_message == "Unexpected failure in LoggingNotificationChannel."


class TestControlledTransportErrorsArePreserved:
    """§31.x: un error controlado de transporte conserva su mensaje
    exacto (información operativa útil), acotado solo por
    MAX_DELIVERY_ERROR_LENGTH -- nunca reemplazado por el mensaje
    genérico."""

    @pytest.mark.parametrize("expected,transport_factory,channel_factory", [
        ("Telegram API request failed (HTTP 500).",
         lambda exc: FakeTelegramTransport(fail_times=1, raises=exc),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock)),
        ("Slack webhook returned an unsuccessful response.",
         lambda exc: FakeSlackTransport(fail_times=1, raises=exc),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock)),
        ("SMTP authentication failed.",
         lambda exc: FakeEmailTransport(fail_times=1, raises=exc),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock)),
        ("Webhook request failed (HTTP 400).",
         lambda exc: FakeWebhookTransport(fail_times=1, raises=exc),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock)),
    ])
    def test_controlled_error_message_is_preserved_exactly(self, expected, transport_factory, channel_factory):
        error_classes = {
            "Telegram API request failed (HTTP 500).": TelegramTransportError,
            "Slack webhook returned an unsuccessful response.": SlackTransportError,
            "SMTP authentication failed.": EmailTransportError,
            "Webhook request failed (HTTP 400).": WebhookTransportError,
        }
        exc = error_classes[expected](expected)
        transport = transport_factory(exc)
        channel = channel_factory(transport, FixedClock(_now()))
        result = channel.deliver(_message())
        assert result.success is False
        assert result.error_message == expected


class TestSecretsNeverInRepresentationContract:
    """§31, punto 19: bot_token/webhook/username/password/endpoint/
    authorization_secret nunca aparecen en repr/str de config/
    transport/channel. Deliberadamente NO incluye chat_id/direcciones de
    email como "secretos": son identificadores de destino, no
    credenciales -- ninguno de los value objects existentes los oculta
    (`TelegramCredentials.chat_id`/`SmtpEmailConfig.sender`/`recipient`
    son campos públicos sin `field(repr=False)`), consistente en todo
    el subsistema."""

    def test_telegram_bot_token_absent(self):
        from src.paper_trading.telegram_transport import TelegramCredentials, UrllibTelegramTransport

        secret = "TELEGRAM-SECRET-TOKEN-999"
        credentials = TelegramCredentials(bot_token=secret, chat_id="chat-1")
        transport = UrllibTelegramTransport(credentials=credentials, timeout_seconds=5.0)
        channel = TelegramNotificationChannel(transport=transport)
        for obj in (credentials, transport, channel):
            assert secret not in repr(obj)
            assert secret not in str(obj)

    def test_slack_webhook_absent(self):
        from src.paper_trading.slack_transport import SlackWebhookConfig, UrllibSlackTransport

        secret_path = "FAKE-SLACK-SECRET-PATH-999"
        webhook_url = f"https://hooks.slack.com/services/T000/B000/{secret_path}"
        config = SlackWebhookConfig(webhook_url=webhook_url)
        transport = UrllibSlackTransport(config=config, timeout_seconds=5.0)
        channel = SlackNotificationChannel(transport=transport)
        for obj in (config, transport, channel):
            assert secret_path not in repr(obj)
            assert secret_path not in str(obj)

    def test_email_username_and_password_absent(self):
        from src.paper_trading.email_transport import SmtpEmailConfig, SmtpEmailTransport

        secret_user = "EMAIL-SECRET-USER-999"
        secret_pass = "EMAIL-SECRET-PASS-999"
        config = SmtpEmailConfig(
            host="smtp.example.com", port=587, sender="a@example.com", recipient="b@example.com",
            security="starttls", username=secret_user, password=secret_pass,
        )
        transport = SmtpEmailTransport(config=config, timeout_seconds=5.0)
        channel = EmailNotificationChannel(transport=transport)
        for obj in (config, transport, channel):
            assert secret_user not in repr(obj)
            assert secret_pass not in repr(obj)
            assert secret_user not in str(obj)
            assert secret_pass not in str(obj)

    def test_webhook_endpoint_and_authorization_secret_absent(self):
        from src.paper_trading.webhook_transport import WebhookEndpointConfig, UrllibWebhookTransport

        secret_path = "webhook-secret-path-abc999"
        secret_auth = "webhooksecretauth999"
        config = WebhookEndpointConfig(
            endpoint_url=f"https://example.com/{secret_path}", authorization_secret=secret_auth,
        )
        transport = UrllibWebhookTransport(config=config, timeout_seconds=5.0)
        channel = WebhookNotificationChannel(transport=transport)
        for obj in (config, transport, channel):
            assert secret_path not in repr(obj)
            assert secret_auth not in repr(obj)
            assert secret_path not in str(obj)
            assert secret_auth not in str(obj)


class TestCompositionOrderContract:
    """§31, punto 9: orden determinista Logging -> Telegram -> Slack ->
    Email -> Webhook, sin depender de diccionarios; deshabilitar un
    canal no altera el orden relativo de los demás."""

    _ALL_CLASSES_IN_ORDER = [
        LoggingNotificationChannel, TelegramNotificationChannel, SlackNotificationChannel,
        EmailNotificationChannel, WebhookNotificationChannel,
    ]

    def _build(self, enabled_names: set):
        channels = []
        for name, factory in _ALL_FIVE_CHANNEL_FACTORIES:
            if name in enabled_names:
                channels.append(factory(FixedClock(_now())))
        return channels

    def test_all_five_enabled_produces_exact_order(self):
        channels = self._build({c.__name__ for c in self._ALL_CLASSES_IN_ORDER})
        assert [type(c) for c in channels] == self._ALL_CLASSES_IN_ORDER

    @pytest.mark.parametrize("disabled_name", [c.__name__ for c in _ALL_CLASSES_IN_ORDER])
    def test_disabling_one_channel_preserves_relative_order_of_others(self, disabled_name):
        enabled = {c.__name__ for c in self._ALL_CLASSES_IN_ORDER} - {disabled_name}
        channels = self._build(enabled)
        expected = [c for c in self._ALL_CLASSES_IN_ORDER if c.__name__ != disabled_name]
        assert [type(c) for c in channels] == expected

    def test_only_logging_and_webhook_preserves_relative_order(self):
        channels = self._build({"LoggingNotificationChannel", "WebhookNotificationChannel"})
        assert [type(c) for c in channels] == [LoggingNotificationChannel, WebhookNotificationChannel]


class TestPersistentIdentityContract:
    """§31, punto 8: type(channel).__name__ sigue siendo la identidad
    persistida; ningún canal fue renombrado."""

    @pytest.mark.parametrize("expected_name,factory", _ALL_FIVE_CHANNEL_FACTORIES)
    def test_class_name_matches_expected_identity(self, expected_name, factory):
        channel = factory(FixedClock(_now()))
        assert type(channel).__name__ == expected_name


class TestCompositeChannelStructuralContract:
    def test_does_not_mutate_the_received_list(self, tmp_path):
        repo = _repo(tmp_path)
        original_list = [LoggingNotificationChannel(clock=FixedClock(_now()))]
        composite = CompositeNotificationChannel(original_list, repository=repo, max_attempts=3, clock=FixedClock(_now()))
        original_list.append(NullNotificationChannel(clock=FixedClock(_now())))
        # El Composite conservó su propia copia -- mutar la lista original
        # después de construirlo no debe afectar cuántos canales invoca.
        assert len(composite._channels) == 1

    def test_repr_has_no_attribute_dump(self, tmp_path):
        """Confirma que `CompositeNotificationChannel` no define un
        `__repr__`/`__str__` propio que vuelque sus atributos -- usa el
        repr por defecto de Python (`<ClassName object at 0x...>`, sin
        `=`), nunca uno estilo dataclass que muestre `_repository=...`/
        `_channels=...`."""
        repo = _repo(tmp_path)
        composite = CompositeNotificationChannel([], repository=repo, max_attempts=3, clock=FixedClock(_now()))
        representation = repr(composite)
        assert "=" not in representation
        assert representation.startswith("<") and "object at 0x" in representation

    def test_single_channel_composite_works(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert()
        _seed_alert(repo, alert)
        composite = CompositeNotificationChannel(
            [LoggingNotificationChannel(clock=FixedClock(_now()))], repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        result = composite.deliver(_message())
        assert result.success is True


class TestTemplateConsistencyAcrossChannels:
    """§31, punto 27: los 5 canales parten del mismo NotificationMessage
    -- mismo alert_id/título/cuerpo conceptual/severidad, adaptado por
    cada formatter/payload, nunca reconstruido desde InspectionAlert."""

    def test_same_message_produces_consistent_content_across_channels(self):
        message = NotificationMessage(
            alert_id="alert-consistency", title="Titulo consistente", body="Cuerpo consistente",
            severity=IssueSeverity.CRITICAL,
        )

        from src.paper_trading.notification_channels import (
            _build_webhook_payload, _format_email_body, _format_email_subject, _format_slack_text,
            _format_telegram_text,
        )

        telegram_text = _format_telegram_text(message)
        slack_text = _format_slack_text(message)
        email_subject = _format_email_subject(message)
        email_body = _format_email_body(message)
        webhook_payload = _build_webhook_payload(message)

        for text in (telegram_text, slack_text, email_body):
            assert "Titulo consistente" in text
            assert "Cuerpo consistente" in text
            assert "CRITICAL" in text

        assert "Titulo consistente" in email_subject
        assert webhook_payload["alert"]["id"] == "alert-consistency"
        assert webhook_payload["alert"]["title"] == "Titulo consistente"
        assert webhook_payload["alert"]["body"] == "Cuerpo consistente"
        assert webhook_payload["alert"]["severity"] == "CRITICAL"

    def test_no_channel_reconstructs_inspection_alert(self):
        """Confirmación estructural: ningún formatter/canal IMPORTA la
        clase `InspectionAlert` en sí (distinta de
        `InspectionAlertChannelDelivery`, el registro de estado de
        entrega por canal, que sí se importa legítimamente y contiene
        "InspectionAlert" como substring de su propio nombre). Se
        compara por palabra completa, con límites de identificador."""
        import re

        import src.paper_trading.notification_channels as module

        source = open(module.__file__, encoding="utf-8").read()
        import_lines = [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
        assert not any(re.search(r"\bInspectionAlert\b", line) for line in import_lines)


class TestSequentialDeliveryDocumented:
    """§31, punto 23: la entrega multicanal es secuencial y determinista
    -- sin concurrencia nueva. Confirmación estructural: el módulo no
    importa threading/asyncio/multiprocessing/concurrent.futures."""

    def test_no_concurrency_primitives_imported(self):
        import src.paper_trading.notification_channels as module

        source = open(module.__file__, encoding="utf-8").read()
        for forbidden in ("import threading", "import asyncio", "import multiprocessing", "concurrent.futures"):
            assert forbidden not in source


class TestObservabilityQueries:
    """§31, punto 21: sin tablas/métricas nuevas, la API existente del
    repositorio ya permite responder qué alerta/canal falló, cuántos
    intentos lleva, el último error sanitizado, cuándo se entregó y el
    estado global."""

    def test_can_answer_operational_questions_from_existing_repository_api(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-obs", deduplication_key="k-obs")
        _seed_alert(repo, alert)

        telegram_fake = FakeTelegramTransport(fail_times=99, error_message="Telegram API request failed (HTTP 401).")
        webhook_fake = FakeWebhookTransport()
        channels = [
            TelegramNotificationChannel(transport=telegram_fake, clock=FixedClock(_now())),
            WebhookNotificationChannel(transport=webhook_fake, clock=FixedClock(_now())),
        ]
        composite = CompositeNotificationChannel(channels, repository=repo, max_attempts=3, clock=FixedClock(_now()))
        composite.deliver(_message(alert_id="alert-obs"))

        # ¿Qué alerta? ¿Estado global?
        global_alert = repo.get_inspection_alert_by_deduplication_key("k-obs")
        assert global_alert.id == "alert-obs"
        assert global_alert.status == AlertStatus.PENDING

        # ¿Qué canal falló? ¿Cuántos intentos? ¿Último error sanitizado? ¿Cuándo se entregó?
        deliveries = {d.channel_name: d for d in repo.fetch_alert_channel_deliveries("alert-obs")}
        assert deliveries["TelegramNotificationChannel"].status == AlertStatus.PENDING
        assert deliveries["TelegramNotificationChannel"].delivery_attempts == 1
        assert "401" in deliveries["TelegramNotificationChannel"].last_error
        assert deliveries["WebhookNotificationChannel"].status == AlertStatus.DELIVERED
        assert deliveries["WebhookNotificationChannel"].delivered_at is not None


class TestMaxAttemptsPerChannelIndependent:
    """§31, punto 17: conteo de intentos por canal, no global; un canal
    exitoso no consume intentos futuros; canales distintos pueden tener
    estados distintos con el mismo max_attempts; no se reinicia al
    reconstruir el Composite (sin reiniciar el proceso)."""

    def test_independent_attempt_counters_and_states(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        alert = _alert(id="alert-attempts", deduplication_key="k-attempts")
        _seed_alert(repo1, alert)

        telegram_fake = FakeTelegramTransport()  # siempre exitoso
        webhook_fake = FakeWebhookTransport(fail_times=99)  # siempre falla
        channels = [
            TelegramNotificationChannel(transport=telegram_fake, clock=FixedClock(_now())),
            WebhookNotificationChannel(transport=webhook_fake, clock=FixedClock(_now())),
        ]
        composite1 = CompositeNotificationChannel(channels, repository=repo1, max_attempts=2, clock=FixedClock(_now()))

        composite1.deliver(_message(alert_id="alert-attempts"))
        composite1.deliver(_message(alert_id="alert-attempts"))
        composite1.deliver(_message(alert_id="alert-attempts"))

        # Telegram tuvo éxito en el primer intento: nunca se reinvoca, nunca consume más intentos.
        assert len(telegram_fake.calls) == 1
        telegram_state = repo1.get_alert_channel_delivery("alert-attempts", "TelegramNotificationChannel")
        assert telegram_state.status == AlertStatus.DELIVERED
        assert telegram_state.delivery_attempts == 1

        # Webhook falla siempre: llega a FAILED al agotar max_attempts=2, y no se reinvoca después.
        assert len(webhook_fake.calls) == 2
        webhook_state = repo1.get_alert_channel_delivery("alert-attempts", "WebhookNotificationChannel")
        assert webhook_state.status == AlertStatus.FAILED
        assert webhook_state.delivery_attempts == 2

        # Reconstrucción del Composite (sin reiniciar el proceso real, pero
        # sobre una nueva instancia de repositorio/objeto): no reinicia contadores.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel(channels, repository=repo2, max_attempts=2, clock=FixedClock(_now()))
        composite2.deliver(_message(alert_id="alert-attempts"))
        assert len(telegram_fake.calls) == 1  # sigue sin repetirse
        assert len(webhook_fake.calls) == 2  # ya FAILED: no se reinvoca


class TestDisabledChannelConfigurationContract:
    """§31, punto 10: cuando un canal externo está deshabilitado, no se
    construye credenciales/config/transporte, no se valida ningún
    secreto/endpoint, y no se requiere ninguna variable de entorno --
    ya cubierto exhaustivamente por test_paper_trading_composition.py
    (TestTelegramChannelWiring/TestSlackChannelWiring/
    TestEmailChannelWiring/TestWebhookChannelWiring); aquí se confirma
    la propiedad transversal en un solo lugar."""

    def test_all_four_external_channels_disabled_by_default(self, tmp_path):
        from decimal import Decimal

        from src.paper_trading.composition import build_paper_trading_context

        class DeterministicIdGenerator:
            def __init__(self):
                self._n = 0

            def _next(self, prefix):
                self._n += 1
                return f"{prefix}-{self._n}"

            def new_order_id(self): return self._next("order")
            def new_execution_id(self): return self._next("exec")
            def new_trade_id(self): return self._next("trade")
            def new_reconciliation_audit_id(self): return self._next("audit")
            def new_inspection_run_id(self): return self._next("run")
            def new_inspection_alert_id(self): return self._next("alert")

        class FakePriceProvider:
            def get_current_price(self, exchange, symbol):
                raise NotImplementedError

            def get_current_prices(self, symbols):
                raise NotImplementedError

        from src.utils.config import PaperTradingConfig

        config = PaperTradingConfig(
            enabled=True, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
            currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("1000"),
            max_position_value=Decimal("5000"), rules_version="v1",
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert len(channels) == 1
        assert isinstance(channels[0], LoggingNotificationChannel)


class TestErrorLengthLimitContract:
    """§31, punto 7: MAX_DELIVERY_ERROR_LENGTH se respeta siempre, con
    excepciones de miles de caracteres, de forma determinista."""

    @pytest.mark.parametrize("name,transport_factory,channel_factory", [
        ("TelegramNotificationChannel", lambda exc: FakeTelegramTransport(fail_times=1, raises=exc),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock)),
        ("SlackNotificationChannel", lambda exc: FakeSlackTransport(fail_times=1, raises=exc),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock)),
        ("EmailNotificationChannel", lambda exc: FakeEmailTransport(fail_times=1, raises=exc),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock)),
        ("WebhookNotificationChannel", lambda exc: FakeWebhookTransport(fail_times=1, raises=exc),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock)),
    ])
    def test_huge_unexpected_exception_produces_short_generic_message(self, name, transport_factory, channel_factory):
        """Etapa 6.16.1 (§31.x): una excepción inesperada, sin importar
        cuán larga sea, nunca se trunca desde su propio contenido -- se
        descarta por completo y se reemplaza por el mensaje genérico
        corto y determinista."""
        huge_message = "z" * 50000
        transport = transport_factory(RuntimeError(huge_message))
        channel = channel_factory(transport, FixedClock(_now()))
        result_1 = channel.deliver(_message())
        transport2 = transport_factory(RuntimeError(huge_message))
        channel2 = channel_factory(transport2, FixedClock(_now()))
        result_2 = channel2.deliver(_message())
        assert result_1.error_message == result_2.error_message  # determinista
        assert result_1.error_message == f"Unexpected failure in {name}."
        assert len(result_1.error_message) <= MAX_DELIVERY_ERROR_LENGTH
        assert huge_message not in result_1.error_message

    @pytest.mark.parametrize("name,transport_factory,channel_factory,error_cls", [
        ("TelegramNotificationChannel", lambda exc: FakeTelegramTransport(fail_times=1, raises=exc),
         lambda t, clock: TelegramNotificationChannel(transport=t, clock=clock), TelegramTransportError),
        ("SlackNotificationChannel", lambda exc: FakeSlackTransport(fail_times=1, raises=exc),
         lambda t, clock: SlackNotificationChannel(transport=t, clock=clock), SlackTransportError),
        ("EmailNotificationChannel", lambda exc: FakeEmailTransport(fail_times=1, raises=exc),
         lambda t, clock: EmailNotificationChannel(transport=t, clock=clock), EmailTransportError),
        ("WebhookNotificationChannel", lambda exc: FakeWebhookTransport(fail_times=1, raises=exc),
         lambda t, clock: WebhookNotificationChannel(transport=t, clock=clock), WebhookTransportError),
    ])
    def test_huge_controlled_error_message_is_truncated_deterministically(
        self, name, transport_factory, channel_factory, error_cls,
    ):
        """Un error controlado (`*TransportError`) inusualmente largo --
        en la práctica los transportes solo producen mensajes estáticos
        cortos, pero esto confirma el mecanismo de truncado en sí --
        también respeta MAX_DELIVERY_ERROR_LENGTH, de forma determinista."""
        huge_message = "z" * 50000
        transport = transport_factory(error_cls(huge_message))
        channel = channel_factory(transport, FixedClock(_now()))
        result_1 = channel.deliver(_message())
        transport2 = transport_factory(error_cls(huge_message))
        channel2 = channel_factory(transport2, FixedClock(_now()))
        result_2 = channel2.deliver(_message())
        assert len(result_1.error_message) == MAX_DELIVERY_ERROR_LENGTH
        assert result_1.error_message == result_2.error_message  # determinista
        assert result_1.error_message.endswith("…")

    def test_composite_aggregate_error_message_is_bounded(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-huge", deduplication_key="k-huge")
        _seed_alert(repo, alert)

        huge_message = "y" * 5000
        channels = [
            TelegramNotificationChannel(transport=FakeTelegramTransport(fail_times=1, raises=RuntimeError(huge_message)), clock=FixedClock(_now())),
            SlackNotificationChannel(transport=FakeSlackTransport(fail_times=1, raises=RuntimeError(huge_message)), clock=FixedClock(_now())),
        ]
        composite = CompositeNotificationChannel(channels, repository=repo, max_attempts=3, clock=FixedClock(_now()))
        result = composite.deliver(_message(alert_id="alert-huge"))
        assert result.success is False
        assert len(result.error_message) <= MAX_DELIVERY_ERROR_LENGTH


class TestAllExternalChannelsFailSimultaneously:
    """§31, punto 16: Logging exitoso, los 4 canales externos fallan a
    la vez -- ningún estado se pierde ni se sobrescribe, cada canal se
    reintenta individualmente."""

    def test_logging_succeeds_four_external_fail(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-allfail", deduplication_key="k-allfail")
        _seed_alert(repo, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_fake = FakeTelegramTransport(fail_times=99, error_message="Telegram failure A.")
        slack_fake = FakeSlackTransport(fail_times=99, error_message="Slack failure B.")
        email_fake = FakeEmailTransport(fail_times=99, error_message="Email failure C.")
        webhook_fake = FakeWebhookTransport(fail_times=99, error_message="Webhook failure D.")

        channels = [
            logging_channel,
            TelegramNotificationChannel(transport=telegram_fake, clock=FixedClock(_now())),
            SlackNotificationChannel(transport=slack_fake, clock=FixedClock(_now())),
            EmailNotificationChannel(transport=email_fake, clock=FixedClock(_now())),
            WebhookNotificationChannel(transport=webhook_fake, clock=FixedClock(_now())),
        ]
        composite = CompositeNotificationChannel(channels, repository=repo, max_attempts=3, clock=FixedClock(_now()))
        service = AlertDeliveryService(repo, composite, max_attempts=3, clock=FixedClock(_now()))
        result = service.deliver_pending_alerts()

        assert result.failed_count == 1
        assert repo.get_inspection_alert_by_deduplication_key("k-allfail").status == AlertStatus.PENDING

        deliveries = {d.channel_name: d for d in repo.fetch_alert_channel_deliveries("alert-allfail")}
        assert deliveries["LoggingNotificationChannel"].status == AlertStatus.DELIVERED
        assert deliveries["TelegramNotificationChannel"].status == AlertStatus.PENDING
        assert deliveries["SlackNotificationChannel"].status == AlertStatus.PENDING
        assert deliveries["EmailNotificationChannel"].status == AlertStatus.PENDING
        assert deliveries["WebhookNotificationChannel"].status == AlertStatus.PENDING

        # Cada mensaje de error es independiente -- ninguno sobrescribe a otro.
        assert "Telegram failure A." in deliveries["TelegramNotificationChannel"].last_error
        assert "Slack failure B." in deliveries["SlackNotificationChannel"].last_error
        assert "Email failure C." in deliveries["EmailNotificationChannel"].last_error
        assert "Webhook failure D." in deliveries["WebhookNotificationChannel"].last_error

        # Segundo intento: cada canal fallido se reintenta individualmente
        # (Logging, ya DELIVERED, no se reinvoca).
        service.deliver_pending_alerts()
        assert len(telegram_fake.calls) == 2
        assert len(slack_fake.calls) == 2
        assert len(email_fake.calls) == 2
        assert len(webhook_fake.calls) == 2


class TestFullIdempotencyAndRetryMatrix:
    """§31, punto 15: escenario completo de 5 canales con reintentos
    escalonados, tal como lo exige la Etapa 6.16 -- construido sobre
    AlertDeliveryService (no solo el Composite) para validar también la
    persistencia del estado global de la alerta en cada ronda."""

    def test_staggered_failures_converge_to_delivered_without_repeats(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo1 = SQLitePaperTradingRepository(db_path)
        repo1.init()
        alert = _alert(id="alert-matrix", deduplication_key="k-matrix")
        _seed_alert(repo1, alert)

        logging_channel = LoggingNotificationChannel(clock=FixedClock(_now()))
        telegram_fake = FakeTelegramTransport()
        slack_fake = FakeSlackTransport()
        # Email falla 2 veces (ronda 1 y 2), tiene éxito en la ronda 3.
        email_fake = FakeEmailTransport(fail_times=2)
        # Webhook falla 3 veces (rondas 1, 2 y 3), tiene éxito en la ronda 4.
        webhook_fake = FakeWebhookTransport(fail_times=3)

        telegram_channel = TelegramNotificationChannel(transport=telegram_fake, clock=FixedClock(_now()))
        slack_channel = SlackNotificationChannel(transport=slack_fake, clock=FixedClock(_now()))
        email_channel = EmailNotificationChannel(transport=email_fake, clock=FixedClock(_now()))
        webhook_channel = WebhookNotificationChannel(transport=webhook_fake, clock=FixedClock(_now()))

        channels = [logging_channel, telegram_channel, slack_channel, email_channel, webhook_channel]
        composite1 = CompositeNotificationChannel(channels, repository=repo1, max_attempts=5, clock=FixedClock(_now()))
        service1 = AlertDeliveryService(repo1, composite1, max_attempts=5, clock=FixedClock(_now()))

        # Ronda 1: Logging/Telegram/Slack exitosos; Email y Webhook fallan.
        service1.deliver_pending_alerts()
        assert repo1.get_alert_channel_delivery("alert-matrix", "LoggingNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-matrix", "TelegramNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-matrix", "SlackNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-matrix", "EmailNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_alert_channel_delivery("alert-matrix", "WebhookNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_inspection_alert_by_deduplication_key("k-matrix").status == AlertStatus.PENDING

        # Ronda 2: Logging/Telegram/Slack no se repiten; Email y Webhook se reintentan (siguen fallando).
        service1.deliver_pending_alerts()
        assert len(telegram_fake.calls) == 1
        assert len(slack_fake.calls) == 1
        assert len(email_fake.calls) == 2
        assert len(webhook_fake.calls) == 2
        assert repo1.get_alert_channel_delivery("alert-matrix", "EmailNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_alert_channel_delivery("alert-matrix", "WebhookNotificationChannel").status == AlertStatus.PENDING

        # Ronda 3: Email tiene éxito; Webhook sigue fallando. Solo esos dos se reintentan.
        service1.deliver_pending_alerts()
        assert len(telegram_fake.calls) == 1
        assert len(slack_fake.calls) == 1
        assert len(email_fake.calls) == 3
        assert len(webhook_fake.calls) == 3
        assert repo1.get_alert_channel_delivery("alert-matrix", "EmailNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_alert_channel_delivery("alert-matrix", "WebhookNotificationChannel").status == AlertStatus.PENDING
        assert repo1.get_inspection_alert_by_deduplication_key("k-matrix").status == AlertStatus.PENDING

        # Ronda 4: solo Webhook se reintenta (el resto ya DELIVERED); tiene éxito. Alerta global -> DELIVERED.
        service1.deliver_pending_alerts()
        assert len(telegram_fake.calls) == 1
        assert len(slack_fake.calls) == 1
        assert len(email_fake.calls) == 3  # ya DELIVERED, no se repite
        assert len(webhook_fake.calls) == 4
        assert repo1.get_alert_channel_delivery("alert-matrix", "WebhookNotificationChannel").status == AlertStatus.DELIVERED
        assert repo1.get_inspection_alert_by_deduplication_key("k-matrix").status == AlertStatus.DELIVERED

        # "Reinicio": ningún canal se vuelve a ejecutar.
        repo2 = SQLitePaperTradingRepository(db_path)
        repo2.init()
        composite2 = CompositeNotificationChannel(channels, repository=repo2, max_attempts=5, clock=FixedClock(_now()))
        service2 = AlertDeliveryService(repo2, composite2, max_attempts=5, clock=FixedClock(_now()))
        result2 = service2.deliver_pending_alerts()
        assert result2.delivered_count == 0
        assert result2.failed_count == 0
        assert len(telegram_fake.calls) == 1
        assert len(slack_fake.calls) == 1
        assert len(email_fake.calls) == 3
        assert len(webhook_fake.calls) == 4


class TestFormatterFailureSanitization:
    """§31.x, punto 16: si un formatter/constructor de payload lanza una
    excepción inesperada con contenido sensible, el resultado debe ser
    genérico y nunca filtrar el contenido -- verificado inyectando la
    excepción vía `unittest.mock.patch` sobre la función del módulo
    (Python resuelve la referencia en tiempo de llamada, así que el
    parche afecta a `deliver()` sin tocar su código)."""

    def test_telegram_formatter_failure_is_sanitized(self):
        import src.paper_trading.notification_channels as module

        channel = TelegramNotificationChannel(transport=FakeTelegramTransport())
        with patch.object(module, "_format_telegram_text", side_effect=RuntimeError(_SENSITIVE_EXCEPTION_TEXT)):
            result = channel.deliver(_message())
        assert result.success is False
        assert result.error_message == "Unexpected failure in TelegramNotificationChannel."

    def test_slack_formatter_failure_is_sanitized(self):
        import src.paper_trading.notification_channels as module

        channel = SlackNotificationChannel(transport=FakeSlackTransport())
        with patch.object(module, "_format_slack_text", side_effect=RuntimeError(_SENSITIVE_EXCEPTION_TEXT)):
            result = channel.deliver(_message())
        assert result.success is False
        assert result.error_message == "Unexpected failure in SlackNotificationChannel."

    def test_email_subject_formatter_failure_is_sanitized(self):
        import src.paper_trading.notification_channels as module

        channel = EmailNotificationChannel(transport=FakeEmailTransport())
        with patch.object(module, "_format_email_subject", side_effect=RuntimeError(_SENSITIVE_EXCEPTION_TEXT)):
            result = channel.deliver(_message())
        assert result.success is False
        assert result.error_message == "Unexpected failure in EmailNotificationChannel."

    def test_email_body_formatter_failure_is_sanitized(self):
        import src.paper_trading.notification_channels as module

        channel = EmailNotificationChannel(transport=FakeEmailTransport())
        with patch.object(module, "_format_email_body", side_effect=RuntimeError(_SENSITIVE_EXCEPTION_TEXT)):
            result = channel.deliver(_message())
        assert result.success is False
        assert result.error_message == "Unexpected failure in EmailNotificationChannel."

    def test_webhook_payload_builder_failure_is_sanitized(self):
        import src.paper_trading.notification_channels as module

        channel = WebhookNotificationChannel(transport=FakeWebhookTransport())
        with patch.object(module, "_build_webhook_payload", side_effect=RuntimeError(_SENSITIVE_EXCEPTION_TEXT)):
            result = channel.deliver(_message())
        assert result.success is False
        assert result.error_message == "Unexpected failure in WebhookNotificationChannel."
        for forbidden in ("SECRET-ABC123", "hunter2", "secret.example", "TOP-SECRET", "Authorization"):
            assert forbidden not in result.error_message


class TestCompositeDefensiveSanitization:
    """§31.x, punto 17: un canal defectuoso que lanza directamente (en
    vez de devolver su propio AlertDeliveryResult fallido, violando su
    contrato) nunca debe filtrar contenido sensible a través de
    CompositeNotificationChannel -- defensa en profundidad."""

    class ExplodingChannel:
        def deliver(self, message):
            raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    def test_exploding_channel_does_not_propagate_and_next_channel_still_runs(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-explode", deduplication_key="k-explode")
        _seed_alert(repo, alert)

        exploding = self.ExplodingChannel()
        webhook_fake = FakeWebhookTransport()
        webhook_channel = WebhookNotificationChannel(transport=webhook_fake, clock=FixedClock(_now()))

        composite = CompositeNotificationChannel(
            [exploding, webhook_channel], repository=repo, max_attempts=3, clock=FixedClock(_now()),
        )
        result = composite.deliver(_message(alert_id="alert-explode"))  # no debe lanzar

        # El canal posterior se procesó igual.
        assert len(webhook_fake.calls) == 1
        webhook_state = repo.get_alert_channel_delivery("alert-explode", "WebhookNotificationChannel")
        assert webhook_state.status == AlertStatus.DELIVERED

        # El canal explosivo queda en un estado fallido según la política existente (PENDING, bajo max_attempts).
        exploding_state = repo.get_alert_channel_delivery("alert-explode", "ExplodingChannel")
        assert exploding_state.status == AlertStatus.PENDING
        assert exploding_state.last_error is not None
        assert len(exploding_state.last_error) <= MAX_DELIVERY_ERROR_LENGTH

        for forbidden in ("SECRET-ABC123", "hunter2", "secret.example", "TOP-SECRET", "Authorization"):
            assert forbidden not in exploding_state.last_error
            assert forbidden not in result.error_message

        assert result.success is False
        assert len(result.error_message) <= MAX_DELIVERY_ERROR_LENGTH
        assert exploding_state.last_error == "Unexpected failure in ExplodingChannel."


class TestAlertDeliveryServiceDefensiveSanitization:
    """§31.x, punto 18: un sink/canal defectuoso que lanza directamente
    nunca debe filtrar contenido sensible a través de
    AlertDeliveryService -- ni en el AlertDeliveryResult ni en
    InspectionAlert.last_error persistido."""

    class ExplodingSink:
        def deliver(self, message):
            raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    def test_exploding_sink_result_and_persisted_alert_are_sanitized(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _alert(id="alert-explode-service", deduplication_key="k-explode-service")
        _seed_alert(repo, alert)

        service = AlertDeliveryService(repo, self.ExplodingSink(), max_attempts=3, clock=FixedClock(_now()))
        batch_result = service.deliver_pending_alerts()

        assert batch_result.failed_count == 1
        persisted = repo.get_inspection_alert_by_deduplication_key("k-explode-service")
        assert persisted.status == AlertStatus.PENDING
        assert persisted.last_error is not None
        assert len(persisted.last_error) <= MAX_DELIVERY_ERROR_LENGTH

        for forbidden in ("SECRET-ABC123", "hunter2", "secret.example", "TOP-SECRET", "Authorization"):
            assert forbidden not in persisted.last_error

        assert persisted.last_error == "Unexpected alert delivery failure."
