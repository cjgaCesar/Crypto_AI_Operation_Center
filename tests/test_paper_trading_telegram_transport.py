"""
Pruebas para src/paper_trading/telegram_transport.py (Etapa 6.12).

Nunca realiza conexiones reales: `urllib.request.urlopen` siempre se
reemplaza con un doble de prueba vía monkeypatch. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §27.
"""

import json
import urllib.error
import urllib.request

import pytest

from src.paper_trading.telegram_transport import (
    TelegramTransportError, UrllibTelegramTransport,
)


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


class TestSuccessfulSend:
    def test_ok_true_response_does_not_raise(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport()
        transport.send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)

    def test_generates_exactly_one_request(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        transport = UrllibTelegramTransport()
        transport.send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)
        assert len(fake.calls) == 1


class TestRequestConstruction:
    def test_uses_post_method(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)
        assert fake.calls[0]["request"].get_method() == "POST"

    def test_includes_chat_id_in_body(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        UrllibTelegramTransport().send_message(bot_token="t", chat_id="chat-123", timeout_seconds=5.0, text="hola")
        body = fake.calls[0]["request"].data.decode("utf-8")
        assert "chat_id=chat-123" in body

    def test_includes_text_in_body(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", timeout_seconds=5.0, text="mensaje de prueba")
        body = fake.calls[0]["request"].data.decode("utf-8")
        assert "mensaje" in body

    def test_timeout_is_passed_to_urlopen(self, monkeypatch):
        fake = _install_fake_urlopen(monkeypatch, body=b'{"ok": true}')
        UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=7.5)
        assert fake.calls[0]["timeout"] == 7.5


class TestErrorHandling:
    def test_ok_false_response_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        with pytest.raises(TelegramTransportError):
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)

    def test_missing_ok_field_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"result": {}}')
        with pytest.raises(TelegramTransportError):
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)

    def test_invalid_json_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"not json at all")
        with pytest.raises(TelegramTransportError) as exc_info:
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)
        assert "invalid JSON" in str(exc_info.value)

    def test_empty_response_body_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"")
        with pytest.raises(TelegramTransportError):
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)

    def test_http_error_raises_transport_error(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url="https://api.telegram.org/x", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        _install_fake_urlopen(monkeypatch, raises=http_error)
        with pytest.raises(TelegramTransportError) as exc_info:
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)
        assert "401" in str(exc_info.value)

    def test_url_error_raises_transport_error(self, monkeypatch):
        url_error = urllib.error.URLError("name resolution failed")
        _install_fake_urlopen(monkeypatch, raises=url_error)
        with pytest.raises(TelegramTransportError):
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)

    def test_timeout_raises_transport_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, raises=TimeoutError("timed out"))
        with pytest.raises(TelegramTransportError) as exc_info:
            UrllibTelegramTransport().send_message(bot_token="t", chat_id="c", text="hola", timeout_seconds=5.0)
        assert "timeout" in str(exc_info.value).lower()


class TestSecretsNeverLeaked:
    def test_token_never_appears_in_http_error_message(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url="https://api.telegram.org/botSECRET-TOKEN-VALUE/sendMessage",
            code=404, msg="Not Found", hdrs=None, fp=None,
        )
        _install_fake_urlopen(monkeypatch, raises=http_error)
        with pytest.raises(TelegramTransportError) as exc_info:
            UrllibTelegramTransport().send_message(
                bot_token="SECRET-TOKEN-VALUE", chat_id="c", text="hola", timeout_seconds=5.0,
            )
        assert "SECRET-TOKEN-VALUE" not in str(exc_info.value)

    def test_token_never_appears_in_invalid_json_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b"garbage")
        with pytest.raises(TelegramTransportError) as exc_info:
            UrllibTelegramTransport().send_message(
                bot_token="SECRET-TOKEN-VALUE", chat_id="c", text="hola", timeout_seconds=5.0,
            )
        assert "SECRET-TOKEN-VALUE" not in str(exc_info.value)

    def test_token_never_appears_in_ok_false_error(self, monkeypatch):
        _install_fake_urlopen(monkeypatch, body=b'{"ok": false}')
        with pytest.raises(TelegramTransportError) as exc_info:
            UrllibTelegramTransport().send_message(
                bot_token="SECRET-TOKEN-VALUE", chat_id="c", text="hola", timeout_seconds=5.0,
            )
        assert "SECRET-TOKEN-VALUE" not in str(exc_info.value)
