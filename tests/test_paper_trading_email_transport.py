"""
Pruebas para src/paper_trading/email_transport.py (Etapa 6.14): mismo
patrón de las Etapas 6.12/6.12.1/6.13/6.13.1 para Telegram/Slack,
aplicado a Email SMTP (SmtpEmailConfig, EmailTransport/SmtpEmailTransport).

Nunca realiza conexiones reales: `smtplib.SMTP`/`smtplib.SMTP_SSL`
siempre se reemplazan con un doble de prueba vía monkeypatch. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §29.
"""

import math
import smtplib
import ssl

import pytest

from src.paper_trading.email_transport import (
    EmailTransportError, SmtpEmailConfig, SmtpEmailTransport,
)

_FAKE_HOST = "smtp.example.com"
_FAKE_SENDER = "alerts@example.com"
_FAKE_RECIPIENT = "ops@example.com"
_FAKE_USERNAME = "SECRETUSER"
_FAKE_PASSWORD = "SECRETPASS"


def _config(**overrides) -> SmtpEmailConfig:
    defaults = dict(host=_FAKE_HOST, port=587, sender=_FAKE_SENDER, recipient=_FAKE_RECIPIENT, security="starttls")
    defaults.update(overrides)
    return SmtpEmailConfig(**defaults)


class TestSmtpEmailConfig:
    def test_valid_starttls_construction(self):
        assert _config(security="starttls") is not None

    def test_valid_ssl_construction(self):
        assert _config(security="ssl", port=465) is not None

    @pytest.mark.parametrize("bad_host", ["", "   "])
    def test_empty_or_blank_host_raises(self, bad_host):
        with pytest.raises(ValueError):
            _config(host=bad_host)

    def test_non_string_host_raises(self):
        with pytest.raises(ValueError):
            _config(host=123)

    @pytest.mark.parametrize("bad_host", [
        "https://smtp.example.com",
        "smtp.example.com:587",
        "user@smtp.example.com",
        "smtp.example.com/path",
        "smtp example.com",
    ])
    def test_malformed_host_rejected(self, bad_host):
        with pytest.raises(ValueError) as exc_info:
            _config(host=bad_host)
        assert bad_host not in str(exc_info.value)

    @pytest.mark.parametrize("valid_host", ["smtp.example.com", "mail.example.org", "localhost"])
    def test_bare_hostname_accepted(self, valid_host):
        assert _config(host=valid_host) is not None

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, True, 587.0, "587", math.nan, math.inf, -math.inf])
    def test_invalid_port_rejected(self, bad_port):
        with pytest.raises(ValueError):
            _config(port=bad_port)

    @pytest.mark.parametrize("bad_security", ["none", "plain", "disabled", "", "STARTTLS", "TLS"])
    def test_invalid_security_rejected(self, bad_security):
        with pytest.raises(ValueError):
            _config(security=bad_security)

    def test_username_without_password_rejected(self):
        with pytest.raises(ValueError):
            _config(username=_FAKE_USERNAME)

    def test_password_without_username_rejected(self):
        with pytest.raises(ValueError):
            _config(password=_FAKE_PASSWORD)

    def test_empty_username_rejected(self):
        with pytest.raises(ValueError):
            _config(username="", password=_FAKE_PASSWORD)

    def test_empty_password_rejected(self):
        with pytest.raises(ValueError):
            _config(username=_FAKE_USERNAME, password="")

    def test_blank_username_rejected(self):
        with pytest.raises(ValueError):
            _config(username="   ", password=_FAKE_PASSWORD)

    def test_valid_credentials_accepted(self):
        assert _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD) is not None

    def test_no_credentials_accepted(self):
        assert _config(username=None, password=None) is not None

    def test_valid_sender_accepted(self):
        assert _config(sender="alerts@example.com") is not None

    def test_valid_sender_with_display_name_accepted(self):
        assert _config(sender="Crypto Alerts <alerts@example.com>") is not None

    def test_valid_recipient_accepted(self):
        assert _config(recipient="ops@example.com") is not None

    @pytest.mark.parametrize("bad_address", ["alerts", "@example.com", "alerts@", ""])
    def test_invalid_sender_rejected(self, bad_address):
        with pytest.raises(ValueError):
            _config(sender=bad_address)

    @pytest.mark.parametrize("bad_address", ["alerts", "@example.com", "alerts@", ""])
    def test_invalid_recipient_rejected(self, bad_address):
        with pytest.raises(ValueError):
            _config(recipient=bad_address)

    def test_sender_header_injection_rejected(self):
        malicious = "a@example.com\nBcc: victim@example.com"
        with pytest.raises(ValueError) as exc_info:
            _config(sender=malicious)
        assert "victim@example.com" not in str(exc_info.value)
        assert malicious not in str(exc_info.value)

    def test_recipient_header_injection_rejected(self):
        malicious = "a@example.com\r\nBcc: victim@example.com"
        with pytest.raises(ValueError) as exc_info:
            _config(recipient=malicious)
        assert "victim@example.com" not in str(exc_info.value)

    def test_multiple_sender_addresses_rejected(self):
        with pytest.raises(ValueError):
            _config(sender="a@example.com,b@example.com")

    def test_multiple_recipient_addresses_rejected(self):
        with pytest.raises(ValueError):
            _config(recipient="a@example.com,b@example.com")

    def test_immutable(self):
        import dataclasses

        config = _config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.host = "other.example.com"

    def test_password_absent_from_repr(self):
        config = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        assert _FAKE_PASSWORD not in repr(config)

    def test_password_absent_from_str(self):
        config = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        assert _FAKE_PASSWORD not in str(config)

    def test_username_absent_from_repr(self):
        config = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        assert _FAKE_USERNAME not in repr(config)

    def test_errors_never_include_sensitive_values(self):
        with pytest.raises(ValueError) as exc_info:
            _config(host="smtp example.com")
        assert "smtp example.com" not in str(exc_info.value)

    def test_equality_for_equal_values(self):
        assert _config() == _config()

    def test_inequality_for_different_host(self):
        assert _config() != _config(host="other.example.com")


class _FakeSMTP:
    """Doble de smtplib.SMTP (modo STARTTLS): nunca realiza ninguna
    conexión real."""

    instances: list = []

    def __init__(self, host=None, port=None, timeout=None, raise_on_init=None):
        self.calls: list = []
        self._raise = {}
        if raise_on_init is not None:
            raise raise_on_init
        self.init_args = (host, port, timeout)
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        if self._raise.get("starttls"):
            raise self._raise["starttls"]
        self.calls.append(("starttls", type(context).__name__ if context else None))

    def login(self, username, password):
        if self._raise.get("login"):
            raise self._raise["login"]
        self.calls.append(("login", username, password))

    def send_message(self, msg):
        if self._raise.get("send_message"):
            raise self._raise["send_message"]
        self.calls.append(("send_message", msg["Subject"], msg.get_content().strip(), msg["From"], msg["To"]))

    def quit(self):
        if self._raise.get("quit"):
            raise self._raise["quit"]
        self.calls.append("quit")


def _make_fake_smtp_factory(raise_at=None, exc=None):
    """Fábrica de _FakeSMTP que puede fallar en un paso específico
    ('init'/'ehlo'/'starttls'/'login'/'send_message'/'quit')."""

    def _factory(host=None, port=None, timeout=None):
        if raise_at == "init":
            raise exc
        instance = _FakeSMTP(host=host, port=port, timeout=timeout)
        if raise_at:
            instance._raise[raise_at] = exc
        return instance

    return _factory


class _FakeSMTPSSL:
    instances: list = []

    def __init__(self, host=None, port=None, timeout=None, context=None):
        self.calls: list = []
        self._raise = {}
        self.init_args = (host, port, timeout, type(context).__name__ if context else None)
        _FakeSMTPSSL.instances.append(self)

    def login(self, username, password):
        if self._raise.get("login"):
            raise self._raise["login"]
        self.calls.append(("login", username, password))

    def send_message(self, msg):
        if self._raise.get("send_message"):
            raise self._raise["send_message"]
        self.calls.append(("send_message", msg["Subject"]))

    def quit(self):
        if self._raise.get("quit"):
            raise self._raise["quit"]
        self.calls.append("quit")


def _make_fake_smtp_ssl_factory(raise_at=None, exc=None):
    def _factory(host=None, port=None, timeout=None, context=None):
        if raise_at == "init":
            raise exc
        instance = _FakeSMTPSSL(host=host, port=port, timeout=timeout, context=context)
        if raise_at:
            instance._raise[raise_at] = exc
        return instance

    return _factory


class TestUrllibEmailTransportConstructor:
    def test_receives_config(self):
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        assert transport is not None

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.5, math.nan, math.inf, -math.inf, True, False])
    def test_rejects_invalid_timeout(self, bad_timeout):
        with pytest.raises(ValueError):
            SmtpEmailTransport(config=_config(), timeout_seconds=bad_timeout)

    def test_repr_does_not_contain_password(self):
        cfg = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        transport = SmtpEmailTransport(config=cfg, timeout_seconds=5.0)
        assert _FAKE_PASSWORD not in repr(transport)

    def test_str_does_not_contain_password(self):
        cfg = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        transport = SmtpEmailTransport(config=cfg, timeout_seconds=5.0)
        assert _FAKE_PASSWORD not in str(transport)

    def test_repr_shows_timeout(self):
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        assert "5.0" in repr(transport)


class TestStarttlsFlow:
    def test_uses_smtp_not_smtp_ssl(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(security="starttls"), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        assert len(_FakeSMTP.instances) >= 1

    def test_passes_host_port_and_timeout(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(host="smtp.example.com", port=587), timeout_seconds=7.5)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        assert instance.init_args == ("smtp.example.com", 587, 7.5)

    def test_calls_ehlo_twice_and_starttls(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        assert instance.calls.count("ehlo") == 2
        assert any(isinstance(c, tuple) and c[0] == "starttls" for c in instance.calls)

    def test_starttls_uses_ssl_context(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        starttls_call = next(c for c in instance.calls if isinstance(c, tuple) and c[0] == "starttls")
        assert starttls_call[1] == "SSLContext"

    def test_login_called_when_credentials_present(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        cfg = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        transport = SmtpEmailTransport(config=cfg, timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        assert ("login", _FAKE_USERNAME, _FAKE_PASSWORD) in instance.calls

    def test_login_not_called_without_credentials(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(username=None, password=None), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        assert not any(isinstance(c, tuple) and c[0] == "login" for c in instance.calls)

    def test_sends_exactly_one_message(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        assert sum(1 for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message") == 1

    def test_closes_session(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        assert "quit" in instance.calls


class TestSslFlow:
    def test_uses_smtp_ssl(self, monkeypatch):
        _FakeSMTPSSL.instances = []
        monkeypatch.setattr(smtplib, "SMTP_SSL", _make_fake_smtp_ssl_factory())
        transport = SmtpEmailTransport(config=_config(security="ssl", port=465), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        assert len(_FakeSMTPSSL.instances) == 1

    def test_passes_ssl_context(self, monkeypatch):
        _FakeSMTPSSL.instances = []
        monkeypatch.setattr(smtplib, "SMTP_SSL", _make_fake_smtp_ssl_factory())
        transport = SmtpEmailTransport(config=_config(security="ssl", port=465), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTPSSL.instances[-1]
        assert instance.init_args[3] == "SSLContext"

    def test_does_not_call_starttls(self, monkeypatch):
        _FakeSMTPSSL.instances = []
        monkeypatch.setattr(smtplib, "SMTP_SSL", _make_fake_smtp_ssl_factory())
        transport = SmtpEmailTransport(config=_config(security="ssl", port=465), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTPSSL.instances[-1]
        assert not hasattr(instance, "starttls")

    def test_login_optional(self, monkeypatch):
        _FakeSMTPSSL.instances = []
        monkeypatch.setattr(smtplib, "SMTP_SSL", _make_fake_smtp_ssl_factory())
        cfg = _config(security="ssl", port=465, username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        transport = SmtpEmailTransport(config=cfg, timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTPSSL.instances[-1]
        assert ("login", _FAKE_USERNAME, _FAKE_PASSWORD) in instance.calls

    def test_sends_exactly_one_message(self, monkeypatch):
        _FakeSMTPSSL.instances = []
        monkeypatch.setattr(smtplib, "SMTP_SSL", _make_fake_smtp_ssl_factory())
        transport = SmtpEmailTransport(config=_config(security="ssl", port=465), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTPSSL.instances[-1]
        assert sum(1 for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message") == 1


class TestPayload:
    def test_from_header_correct(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(sender="alerts@example.com"), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        send_call = next(c for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message")
        assert send_call[3] == "alerts@example.com"

    def test_to_header_correct(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(recipient="ops@example.com"), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")
        instance = _FakeSMTP.instances[-1]
        send_call = next(c for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message")
        assert send_call[4] == "ops@example.com"

    def test_subject_correct(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="[Crypto AI] Test", body="B")
        instance = _FakeSMTP.instances[-1]
        send_call = next(c for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message")
        assert send_call[1] == "[Crypto AI] Test"

    def test_body_is_plain_text(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="S", body="Cuerpo de la alerta.")
        instance = _FakeSMTP.instances[-1]
        send_call = next(c for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message")
        assert send_call[2] == "Cuerpo de la alerta."

    def test_utf8_body_roundtrips(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        original_body = "acentuación: áéíóú ñ"
        transport.send_message(subject="S", body=original_body)
        instance = _FakeSMTP.instances[-1]
        send_call = next(c for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message")
        assert send_call[2] == original_body

    def test_send_message_only_accepts_subject_and_body(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory())
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(TypeError):
            transport.send_message(subject="S", body="B", host="other.example.com")


class TestErrorHandling:
    def test_connection_error_raises_transport_error(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory(raise_at="init", exc=ConnectionRefusedError("refused")))
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert "connection" in str(exc_info.value).lower()

    def test_timeout_at_connect_raises_transport_error(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory(raise_at="init", exc=TimeoutError("timed out")))
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert "timed out" in str(exc_info.value).lower()

    def test_ssl_error_raises_transport_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP", _make_fake_smtp_factory(raise_at="starttls", exc=ssl.SSLError("bad handshake")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert "tls" in str(exc_info.value).lower()

    def test_starttls_error_raises_transport_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP", _make_fake_smtp_factory(raise_at="starttls", exc=smtplib.SMTPException("starttls failed")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert "tls" in str(exc_info.value).lower()

    def test_authentication_error_raises_transport_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="login", exc=smtplib.SMTPAuthenticationError(535, b"bad creds")),
        )
        cfg = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        transport = SmtpEmailTransport(config=cfg, timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert "auth" in str(exc_info.value).lower()

    def test_smtp_error_raises_transport_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="send_message", exc=smtplib.SMTPDataError(450, b"mailbox full")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert "delivery" in str(exc_info.value).lower()

    def test_unexpected_exception_is_sanitized(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="init", exc=RuntimeError(f"boom host={_FAKE_HOST} pw={_FAKE_PASSWORD}")),
        )
        cfg = _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)
        transport = SmtpEmailTransport(config=cfg, timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        message = str(exc_info.value)
        assert _FAKE_HOST not in message
        assert _FAKE_PASSWORD not in message

    def test_never_retries_internally(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="send_message", exc=smtplib.SMTPDataError(450, b"mailbox full")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError):
            transport.send_message(subject="S", body="B")
        assert len(_FakeSMTP.instances) == 1


class TestSecretsNeverLeaked:
    def _cfg_with_secrets(self):
        return _config(username=_FAKE_USERNAME, password=_FAKE_PASSWORD)

    def test_password_absent_from_connection_error(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory(raise_at="init", exc=OSError("refused")))
        transport = SmtpEmailTransport(config=self._cfg_with_secrets(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert _FAKE_PASSWORD not in str(exc_info.value)

    def test_username_absent_from_authentication_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="login", exc=smtplib.SMTPAuthenticationError(535, b"bad creds")),
        )
        transport = SmtpEmailTransport(config=self._cfg_with_secrets(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert _FAKE_USERNAME not in str(exc_info.value)

    def test_host_absent_from_any_error(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _make_fake_smtp_factory(raise_at="init", exc=OSError("refused")))
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert _FAKE_HOST not in str(exc_info.value)

    def test_sender_absent_from_any_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="send_message", exc=smtplib.SMTPDataError(450, b"full")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert _FAKE_SENDER not in str(exc_info.value)

    def test_recipient_absent_from_any_error(self, monkeypatch):
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="send_message", exc=smtplib.SMTPDataError(450, b"full")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(EmailTransportError) as exc_info:
            transport.send_message(subject="S", body="B")
        assert _FAKE_RECIPIENT not in str(exc_info.value)

    def test_password_absent_from_repr_and_str(self):
        transport = SmtpEmailTransport(config=self._cfg_with_secrets(), timeout_seconds=5.0)
        assert _FAKE_PASSWORD not in repr(transport)
        assert _FAKE_PASSWORD not in str(transport)


class TestCloseAfterSuccessfulSend:
    """Punto 17: un fallo de quit() posterior a un send_message() exitoso
    nunca se reporta como fallo ni provoca un segundo envío."""

    def test_starttls_quit_failure_after_success_does_not_raise(self, monkeypatch):
        _FakeSMTP.instances = []
        monkeypatch.setattr(
            smtplib, "SMTP",
            _make_fake_smtp_factory(raise_at="quit", exc=smtplib.SMTPServerDisconnected("already disconnected")),
        )
        transport = SmtpEmailTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")  # no debe lanzar

        instance = _FakeSMTP.instances[-1]
        assert sum(1 for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message") == 1

    def test_ssl_quit_failure_after_success_does_not_raise(self, monkeypatch):
        _FakeSMTPSSL.instances = []
        monkeypatch.setattr(
            smtplib, "SMTP_SSL",
            _make_fake_smtp_ssl_factory(raise_at="quit", exc=smtplib.SMTPServerDisconnected("already disconnected")),
        )
        transport = SmtpEmailTransport(config=_config(security="ssl", port=465), timeout_seconds=5.0)
        transport.send_message(subject="S", body="B")  # no debe lanzar

        instance = _FakeSMTPSSL.instances[-1]
        assert sum(1 for c in instance.calls if isinstance(c, tuple) and c[0] == "send_message") == 1
