"""
Pruebas para src/paper_trading/slack_transport.py (Etapa 6.13): mismo
patrón de la Etapa 6.12/6.12.1 para Telegram, aplicado a Slack
(SlackWebhookConfig, SlackTransport/UrllibSlackTransport).

Nunca realiza conexiones reales: `urllib.request.urlopen` siempre se
reemplaza con un doble de prueba vía monkeypatch. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §28.
"""

import dataclasses
import math
import urllib.error
import urllib.request

import pytest

from src.paper_trading.slack_transport import (
    SlackTransportError, SlackWebhookConfig, UrllibSlackTransport,
)

_FAKE_WEBHOOK_URL = "https://hooks.slack.com/services/T000/B000/FAKE-WEBHOOK-VALUE"


def _config(**overrides) -> SlackWebhookConfig:
    defaults = dict(webhook_url=_FAKE_WEBHOOK_URL)
    defaults.update(overrides)
    return SlackWebhookConfig(**defaults)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _RecordingUrlopen:
    def __init__(self, body: bytes = b"ok", raises: Exception = None):
        self.calls: list = []
        self._body = body
        self._raises = raises

    def __call__(self, request, timeout=None):
        self.calls.append({"request": request, "timeout": timeout})
        if self._raises is not None:
            raise self._raises
        return _FakeResponse(self._body)


def _install_fake_urlopen(monkeypatch, **kwargs) -> _RecordingUrlopen:
    fake = _RecordingUrlopen(**kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


class TestSlackWebhookConfig:
    def test_valid_construction(self):
        config = _config()
        assert config is not None

    @pytest.mark.parametrize("bad_url", ["", "   "])
    def test_empty_or_blank_url_raises(self, bad_url):
        with pytest.raises(ValueError):
            _config(webhook_url=bad_url)

    def test_non_string_raises(self):
        with pytest.raises(ValueError):
            _config(webhook_url=123)

    def test_http_scheme_rejected(self):
        with pytest.raises(ValueError):
            _config(webhook_url="http://hooks.slack.com/services/T000/B000/XXXX")

    def test_missing_scheme_rejected(self):
        with pytest.raises(ValueError):
            _config(webhook_url="hooks.slack.com/services/T000/B000/XXXX")

    def test_different_host_rejected(self):
        with pytest.raises(ValueError):
            _config(webhook_url="https://evilslack.com/services/T000/B000/XXXX")

    def test_malicious_subdomain_rejected(self):
        with pytest.raises(ValueError):
            _config(webhook_url="https://hooks.slack.com.example.com/services/T000/B000/XXXX")

    def test_lookalike_host_rejected(self):
        with pytest.raises(ValueError):
            _config(webhook_url="https://evilslack.com/services/T000/B000/XXXX")

    def test_userinfo_spoofing_rejected(self):
        with pytest.raises(ValueError):
            _config(webhook_url="https://hooks.slack.com@evil.com/services/T000/B000/XXXX")

    def test_hooks_slack_com_accepted(self):
        assert _config(webhook_url="https://hooks.slack.com/services/T000/B000/XXXX") is not None

    def test_hooks_slack_gov_com_accepted(self):
        assert _config(webhook_url="https://hooks.slack-gov.com/services/T000/B000/XXXX") is not None

    def test_immutable(self):
        config = _config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.webhook_url = "https://hooks.slack.com/other"

    def test_repr_does_not_contain_webhook(self):
        assert "FAKE-WEBHOOK-VALUE" not in repr(_config())

    def test_str_does_not_contain_webhook(self):
        assert "FAKE-WEBHOOK-VALUE" not in str(_config())

    def test_equality_for_equal_values(self):
        assert _config() == _config()

    def test_inequality_for_different_urls(self):
        assert _config() != _config(webhook_url="https://hooks.slack.com/services/other/other/other")

    def test_validation_messages_never_include_the_rejected_value(self):
        rejected = "https://evilslack.com/should-not-appear-in-error"
        with pytest.raises(ValueError) as exc_info:
            _config(webhook_url=rejected)
        assert rejected not in str(exc_info.value)
        assert "evilslack.com" not in str(exc_info.value)


class TestUrllibSlackTransportConstructor:
    def test_receives_config(self):
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        assert transport is not None

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.5, math.nan, math.inf, -math.inf, True, False])
    def test_rejects_invalid_timeout(self, bad_timeout):
        with pytest.raises(ValueError):
            UrllibSlackTransport(config=_config(), timeout_seconds=bad_timeout)

    def test_repr_does_not_contain_webhook(self):
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        assert "FAKE-WEBHOOK-VALUE" not in repr(transport)

    def test_str_does_not_contain_webhook(self):
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        assert "FAKE-WEBHOOK-VALUE" not in str(transport)

    def test_repr_shows_timeout(self):
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        assert "5.0" in repr(transport)


class TestSuccessfulSend:
    def test_ok_response_does_not_raise(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="hola")

    def test_ok_with_trailing_newline_does_not_raise(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"ok\n")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="hola")

    def test_generates_exactly_one_request(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="hola")
        assert len(fake.calls) == 1

    def test_send_message_only_accepts_text(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(TypeError):
            transport.send_message(text="hola", webhook_url="otro")


class TestRequestUsesEncapsulatedConfiguration:
    def test_uses_post_method(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="hola")
        assert fake.calls[0]["request"].get_method() == "POST"

    def test_uses_configured_webhook_as_url(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        webhook = "https://hooks.slack.com/services/T111/B111/DIFFERENT"
        transport = UrllibSlackTransport(config=_config(webhook_url=webhook), timeout_seconds=5.0)
        transport.send_message(text="hola")
        assert fake.calls[0]["request"].full_url == webhook

    def test_content_type_header_is_json(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="hola")
        headers = fake.calls[0]["request"].headers
        assert headers.get("Content-type") == "application/json; charset=utf-8"

    def test_payload_contains_text_as_json(self, monkeypatch):
        import json

        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="mensaje de prueba")
        body = json.loads(fake.calls[0]["request"].data.decode("utf-8"))
        assert body == {"text": "mensaje de prueba"}

    def test_payload_is_utf8_encoded(self, monkeypatch):
        import json

        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        transport.send_message(text="acentuación: áéíóú ñ")
        raw = fake.calls[0]["request"].data
        assert json.loads(raw.decode("utf-8"))["text"] == "acentuación: áéíóú ñ"

    def test_timeout_is_passed_to_urlopen(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b"ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=8.25)
        transport.send_message(text="hola")
        assert fake.calls[0]["timeout"] == 8.25


class TestErrorHandling:
    def test_empty_response_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError):
            transport.send_message(text="hola")

    def test_response_different_from_ok_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"invalid_payload")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "unsuccessful" in str(exc_info.value).lower()

    def test_undecodable_response_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"\xff\xfe\x00\x01")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "invalid" in str(exc_info.value).lower()

    def test_http_error_raises_transport_error(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url="https://hooks.slack.com/x", code=400, msg="Bad Request", hdrs=None, fp=None,
        )
        _install_fake_urlopen(monkeypatch, raises=http_error)
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "400" in str(exc_info.value)

    def test_url_error_raises_transport_error(self, monkeypatch):
        url_error = urllib.error.URLError("name resolution failed")
        _install_fake_urlopen(monkeypatch, raises=url_error)
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError):
            transport.send_message(text="hola")

    def test_timeout_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, raises=TimeoutError("timed out"))
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "timeout" in str(exc_info.value).lower()

    def test_unexpected_exception_is_sanitized(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, raises=RuntimeError(f"boom webhook={_FAKE_WEBHOOK_URL}"))
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_WEBHOOK_URL not in str(exc_info.value)

    def test_never_retries_internally(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b"not_ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError):
            transport.send_message(text="hola")
        assert len(fake.calls) == 1


class TestSecretsNeverLeaked:
    def test_webhook_never_appears_in_http_error_message(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url=_FAKE_WEBHOOK_URL, code=404, msg="Not Found", hdrs=None, fp=None,
        )
        _install_fake_urlopen(monkeypatch, raises=http_error)
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_WEBHOOK_URL not in str(exc_info.value)

    def test_webhook_never_appears_in_unsuccessful_response_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"not_ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_WEBHOOK_URL not in str(exc_info.value)

    def test_full_url_never_appears_in_any_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"not_ok")
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "hooks.slack.com" not in str(exc_info.value)

    def test_full_response_body_never_appears_in_error(self, monkeypatch):
        sensitive_body = b"sensitive_internal_payload_should_never_leak"
        _install_fake_urlopen(monkeypatch, body=sensitive_body)
        transport = UrllibSlackTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(SlackTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "sensitive_internal_payload_should_never_leak" not in str(exc_info.value)
