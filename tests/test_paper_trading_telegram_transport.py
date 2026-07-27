"""
Pruebas para src/paper_trading/telegram_transport.py (Etapa 6.12,
endurecido en 6.12.1 con TelegramCredentials y un transporte
preconfigurado -- ver docs/ARQUITECTURA_PAPER_TRADING.md §27/§27.x).

Nunca realiza conexiones reales: `urllib.request.urlopen` siempre se
reemplaza con un doble de prueba vía monkeypatch.
"""

import dataclasses
import math
import urllib.error
import urllib.request

import pytest

from src.paper_trading.telegram_transport import (
    TelegramCredentials, TelegramTransportError, UrllibTelegramTransport,
)

_FAKE_TOKEN = "SECRET-TOKEN-VALUE"
_FAKE_CHAT_ID = "chat-42"


def _credentials(**overrides) -> TelegramCredentials:
    defaults = dict(bot_token=_FAKE_TOKEN, chat_id=_FAKE_CHAT_ID)
    defaults.update(overrides)
    return TelegramCredentials(**defaults)


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
    """Doble de `urllib.request.urlopen`: registra la solicitud recibida
    y devuelve una respuesta fija, sin ninguna conexión real."""

    def __init__(self, body: bytes = b'{"ok": true}', raises: Exception = None):
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


class TestTelegramCredentials:
    def test_valid_construction(self):
        creds = _credentials()
        assert creds.chat_id == _FAKE_CHAT_ID

    @pytest.mark.parametrize("bad_token", ["", "   "])
    def test_empty_or_blank_token_raises(self, bad_token):
        with pytest.raises(ValueError):
            _credentials(bot_token=bad_token)

    @pytest.mark.parametrize("bad_chat_id", ["", "   "])
    def test_empty_or_blank_chat_id_raises(self, bad_chat_id):
        with pytest.raises(ValueError):
            _credentials(chat_id=bad_chat_id)

    def test_immutable(self):
        creds = _credentials()
        with pytest.raises(dataclasses.FrozenInstanceError):
            creds.chat_id = "otro"

    def test_repr_does_not_contain_token(self):
        assert _FAKE_TOKEN not in repr(_credentials())

    def test_str_does_not_contain_token(self):
        assert _FAKE_TOKEN not in str(_credentials())

    def test_equality_for_equal_values(self):
        assert _credentials() == _credentials()

    def test_inequality_for_different_chat_id(self):
        assert _credentials(chat_id="other-chat") != _credentials()

    def test_validation_messages_never_include_the_rejected_secret(self):
        secret_value = "MY-REJECTED-SECRET"
        with pytest.raises(ValueError) as exc_info:
            _credentials(bot_token="")
        assert secret_value not in str(exc_info.value)


class TestUrllibTelegramTransportConstructor:
    def test_receives_credentials(self):
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        assert transport is not None

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.5, math.nan, math.inf, -math.inf, True, False])
    def test_rejects_invalid_timeout(self, bad_timeout):
        """Etapa 6.16 (§31, auditoría transversal): `True`/`False` deben
        rechazarse igual que Slack/Email/Webhook -- corrige un defecto
        real detectado en la auditoría (como `bool` es subclase de
        `int`, `timeout_seconds=True` pasaba silenciosamente la
        validación anterior y se aceptaba como 1.0 segundos)."""
        with pytest.raises(ValueError):
            UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=bad_timeout)

    def test_repr_does_not_contain_token(self):
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        assert _FAKE_TOKEN not in repr(transport)

    def test_str_does_not_contain_token(self):
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        assert _FAKE_TOKEN not in str(transport)

    def test_repr_shows_timeout(self):
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        assert "5.0" in repr(transport)


class TestSuccessfulSend:
    def test_ok_true_response_does_not_raise(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        transport.send_message(text="hola")

    def test_generates_exactly_one_request(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        transport.send_message(text="hola")
        assert len(fake.calls) == 1

    def test_send_message_only_accepts_text(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TypeError):
            transport.send_message(text="hola", bot_token="otro")


class TestRequestUsesEncapsulatedConfiguration:
    def test_uses_post_method(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        transport.send_message(text="hola")
        assert fake.calls[0]["request"].get_method() == "POST"

    def test_uses_encapsulated_chat_id_in_body(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(chat_id="chat-123"), timeout_seconds=5.0)
        transport.send_message(text="hola")
        body = fake.calls[0]["request"].data.decode("utf-8")
        assert "chat_id=chat-123" in body

    def test_uses_encapsulated_token_to_build_the_url(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(bot_token="tok-abc"), timeout_seconds=5.0)
        transport.send_message(text="hola")
        assert "tok-abc" in fake.calls[0]["request"].full_url

    def test_includes_text_in_body(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        transport.send_message(text="mensaje de prueba")
        body = fake.calls[0]["request"].data.decode("utf-8")
        assert "mensaje" in body

    def test_timeout_is_passed_to_urlopen(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=7.5)
        transport.send_message(text="hola")
        assert fake.calls[0]["timeout"] == 7.5


class TestErrorHandling:
    def test_ok_false_response_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError):
            transport.send_message(text="hola")

    def test_missing_ok_field_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"result": {}}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError):
            transport.send_message(text="hola")

    def test_invalid_json_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"not json at all")
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "invalid JSON" in str(exc_info.value)

    def test_empty_response_body_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"")
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError):
            transport.send_message(text="hola")

    def test_http_error_raises_transport_error(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url="https://api.telegram.org/x", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        _install_fake_urlopen(monkeypatch, raises=http_error)
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "401" in str(exc_info.value)

    def test_url_error_raises_transport_error(self, monkeypatch):
        url_error = urllib.error.URLError("name resolution failed")
        _install_fake_urlopen(monkeypatch, raises=url_error)
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError):
            transport.send_message(text="hola")

    def test_timeout_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, raises=TimeoutError("timed out"))
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "timeout" in str(exc_info.value).lower()

    def test_unexpected_exception_is_sanitized(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, raises=RuntimeError(f"boom token={_FAKE_TOKEN}"))
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_TOKEN not in str(exc_info.value)

    def test_never_retries_internally(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError):
            transport.send_message(text="hola")
        assert len(fake.calls) == 1


class TestSecretsNeverLeaked:
    def test_token_never_appears_in_http_error_message(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url=f"https://api.telegram.org/bot{_FAKE_TOKEN}/sendMessage",
            code=404, msg="Not Found", hdrs=None, fp=None,
        )
        _install_fake_urlopen(monkeypatch, raises=http_error)
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_TOKEN not in str(exc_info.value)

    def test_token_never_appears_in_invalid_json_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"garbage")
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_TOKEN not in str(exc_info.value)

    def test_token_never_appears_in_ok_false_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_TOKEN not in str(exc_info.value)

    def test_chat_id_never_appears_in_any_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert _FAKE_CHAT_ID not in str(exc_info.value)

    def test_full_url_never_appears_in_any_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        transport = UrllibTelegramTransport(credentials=_credentials(), timeout_seconds=5.0)
        with pytest.raises(TelegramTransportError) as exc_info:
            transport.send_message(text="hola")
        assert "api.telegram.org" not in str(exc_info.value)
