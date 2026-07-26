"""
Pruebas para src/paper_trading/webhook_transport.py (Etapa 6.15): mismo
patrón de las Etapas 6.12/6.13/6.14 para Telegram/Slack/Email, aplicado
a un webhook HTTP genérico (WebhookEndpointConfig,
WebhookTransport/UrllibWebhookTransport).

Nunca realiza conexiones reales: `urllib.request.build_opener` siempre
se reemplaza con un doble de prueba vía monkeypatch (a diferencia de
Slack/Telegram, que monkeypatchean `urllib.request.urlopen`
directamente -- Webhook usa un `opener` propio para poder instalar el
handler que bloquea redirecciones, ver `_NoRedirectHandler`). Ver
docs/ARQUITECTURA_PAPER_TRADING.md §30.
"""

import dataclasses
import json
import math
import urllib.error
import urllib.request

import pytest

from src.paper_trading.webhook_transport import (
    WEBHOOK_MAX_PAYLOAD_BYTES, WebhookEndpointConfig, WebhookTransportError, UrllibWebhookTransport,
    _NoRedirectHandler,
)

_FAKE_ENDPOINT_URL = "https://example.com/hook-path-abc123"
_FAKE_SECRET = "secretvalue789xyz"


def _config(**overrides) -> WebhookEndpointConfig:
    defaults = dict(endpoint_url=_FAKE_ENDPOINT_URL)
    defaults.update(overrides)
    return WebhookEndpointConfig(**defaults)


class _FakeResponse:
    def __init__(self, body: bytes = b""):
        self._body = body

    def read(self, n=None):
        return self._body if n is None else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _RecordingOpener:
    def __init__(self, body: bytes = b"", raises: Exception = None):
        self.calls: list = []
        self._body = body
        self._raises = raises

    def open(self, request, timeout=None):
        self.calls.append({"request": request, "timeout": timeout})
        if self._raises is not None:
            raise self._raises
        return _FakeResponse(self._body)


def _install_fake_opener(monkeypatch, **kwargs) -> _RecordingOpener:
    fake = _RecordingOpener(**kwargs)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args, **kw: fake)
    return fake


class TestWebhookEndpointConfig:
    def test_valid_construction(self):
        assert _config() is not None

    @pytest.mark.parametrize("bad_url", ["", "   "])
    def test_empty_or_blank_url_raises(self, bad_url):
        with pytest.raises(ValueError):
            _config(endpoint_url=bad_url)

    def test_non_string_url_raises(self):
        with pytest.raises(ValueError):
            _config(endpoint_url=123)

    def test_http_scheme_rejected(self):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url="http://example.com/hook")
        assert "HTTPS" in str(exc_info.value)

    @pytest.mark.parametrize("bad_url", [
        "ftp://example.com/hook",
        "file:///etc/passwd",
        "data:text/plain;base64,aGVsbG8=",
        "javascript:alert(1)",
        "example.com/hook",
    ])
    def test_non_https_scheme_rejected(self, bad_url):
        with pytest.raises(ValueError):
            _config(endpoint_url=bad_url)

    def test_host_absent_rejected(self):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url="https:///hook")
        assert "host" in str(exc_info.value).lower()

    def test_userinfo_rejected(self):
        url = "https://secretuser123:secretpass456@example.com/hook"
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url=url)
        message = str(exc_info.value)
        assert "user information" in message.lower()
        assert "secretuser123" not in message
        assert "secretpass456" not in message

    def test_query_string_rejected(self):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url="https://example.com/hook?token=leakedsecret")
        message = str(exc_info.value)
        assert "query string" in message.lower()
        assert "leakedsecret" not in message

    def test_fragment_rejected(self):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url="https://example.com/hook#leakedfragment")
        message = str(exc_info.value)
        assert "fragment" in message.lower()
        assert "leakedfragment" not in message

    def test_default_port_443_accepted(self):
        assert _config(endpoint_url="https://example.com:443/hook") is not None

    def test_no_explicit_port_accepted(self):
        assert _config(endpoint_url="https://example.com/hook") is not None

    @pytest.mark.parametrize("bad_url", [
        "https://example.com:80/hook",
        "https://example.com:8080/hook",
        "https://example.com:8443/hook",
    ])
    def test_non_default_port_rejected(self, bad_url):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url=bad_url)
        message = str(exc_info.value)
        assert "default HTTPS port" in message
        assert "80" not in message.replace("HTTPS", "")

    def test_invalid_port_syntax_is_controlled_failure(self):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url="https://example.com:abc/hook")
        assert "abc" not in str(exc_info.value)

    @pytest.mark.parametrize("path", ["", "/"])
    def test_root_or_empty_path_rejected(self, path):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url=f"https://example.com{path}")
        assert "non-root path" in str(exc_info.value)

    @pytest.mark.parametrize("path", [
        "/../hook",
        "/hook/..",
        "/hook/./x",
        "/%2E%2E/hook",
        "/hook/%2E%2E",
        "/hook%2Fadmin",
    ])
    def test_ambiguous_path_rejected(self, path):
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url=f"https://example.com{path}")
        assert "non-root path" in str(exc_info.value)

    def test_normal_path_accepted(self):
        assert _config(endpoint_url="https://example.com/services/webhook") is not None

    @pytest.mark.parametrize("host", [
        "localhost", "sub.localhost", "127.0.0.1", "127.5.5.5", "0.0.0.0",
    ])
    def test_local_host_rejected(self, host):
        with pytest.raises(ValueError):
            _config(endpoint_url=f"https://{host}/hook")

    @pytest.mark.parametrize("host", [
        "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.1.1",
    ])
    def test_private_ipv4_rejected(self, host):
        with pytest.raises(ValueError):
            _config(endpoint_url=f"https://{host}/hook")

    @pytest.mark.parametrize("host", ["[::1]", "[fc00::1]", "[fe80::1]"])
    def test_private_ipv6_rejected(self, host):
        with pytest.raises(ValueError):
            _config(endpoint_url=f"https://{host}/hook")

    def test_multicast_ipv4_rejected(self):
        with pytest.raises(ValueError):
            _config(endpoint_url="https://224.0.0.1/hook")

    @pytest.mark.parametrize("host", ["8.8.8.8", "example.com", "api.example.org"])
    def test_public_host_accepted(self, host):
        assert _config(endpoint_url=f"https://{host}/hook") is not None

    def test_no_authorization_secret_accepted(self):
        assert _config(authorization_secret=None) is not None

    @pytest.mark.parametrize("bad_secret", ["", "   ", "Bearer abc", "bearer abc", "abc\ndef", "abc\rdef"])
    def test_invalid_authorization_secret_rejected(self, bad_secret):
        with pytest.raises(ValueError) as exc_info:
            _config(authorization_secret=bad_secret)
        assert "Bearer prefix or line breaks" in str(exc_info.value)

    def test_valid_authorization_secret_accepted(self):
        assert _config(authorization_secret=_FAKE_SECRET) is not None

    def test_immutable(self):
        config = _config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.endpoint_url = "https://other.example.com/hook"

    def test_repr_does_not_contain_url_or_secret(self):
        config = _config(authorization_secret=_FAKE_SECRET)
        representation = repr(config)
        assert _FAKE_ENDPOINT_URL not in representation
        assert _FAKE_SECRET not in representation

    def test_str_does_not_contain_url_or_secret(self):
        config = _config(authorization_secret=_FAKE_SECRET)
        representation = str(config)
        assert _FAKE_ENDPOINT_URL not in representation
        assert _FAKE_SECRET not in representation

    def test_equality_for_equal_values(self):
        assert _config() == _config()

    def test_inequality_for_different_urls(self):
        assert _config() != _config(endpoint_url="https://other.example.com/hook")

    def test_validation_messages_never_include_the_rejected_url(self):
        rejected = "https://192.168.99.99/should-not-appear-in-error"
        with pytest.raises(ValueError) as exc_info:
            _config(endpoint_url=rejected)
        assert rejected not in str(exc_info.value)
        assert "192.168.99.99" not in str(exc_info.value)


class TestNoRedirectHandler:
    """Verifica directamente que el handler personalizado (§30, punto 22)
    bloquea toda redirección, para cada código exigido por la Etapa
    6.15 (301/302/303/307/308) -- nunca construye una segunda solicitud."""

    @pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
    def test_redirect_request_raises_http_error(self, code):
        handler = _NoRedirectHandler()
        req = urllib.request.Request(_FAKE_ENDPOINT_URL, method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            handler.redirect_request(req, None, code, "redirected", {}, "https://evil.example/steal")
        assert exc_info.value.code == code


class TestUrllibWebhookTransportConstructor:
    def test_receives_config(self):
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        assert transport is not None

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.5, math.nan, math.inf, -math.inf, True, False])
    def test_rejects_invalid_timeout(self, bad_timeout):
        with pytest.raises(ValueError):
            UrllibWebhookTransport(config=_config(), timeout_seconds=bad_timeout)

    def test_repr_does_not_contain_url_or_secret(self):
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        representation = repr(transport)
        assert _FAKE_ENDPOINT_URL not in representation
        assert _FAKE_SECRET not in representation

    def test_str_does_not_contain_url_or_secret(self):
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        representation = str(transport)
        assert _FAKE_ENDPOINT_URL not in representation
        assert _FAKE_SECRET not in representation

    def test_repr_shows_timeout(self):
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        assert "5.0" in repr(transport)


class TestSuccessfulSend:
    def test_2xx_range_does_not_raise(self, monkeypatch):
        _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})

    def test_generates_exactly_one_request(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        assert len(fake.calls) == 1

    def test_empty_response_body_is_accepted(self, monkeypatch):
        _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})

    def test_send_payload_only_accepts_payload(self, monkeypatch):
        _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(TypeError):
            transport.send_payload(payload={"a": 1}, endpoint_url="other")


class TestRequestConstruction:
    def test_uses_post_method(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        assert fake.calls[0]["request"].get_method() == "POST"

    def test_uses_configured_endpoint_as_url(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        endpoint = "https://example.com/services/other-hook"
        transport = UrllibWebhookTransport(config=_config(endpoint_url=endpoint), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        assert fake.calls[0]["request"].full_url == endpoint

    def test_content_type_header(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        headers = fake.calls[0]["request"].headers
        assert headers.get("Content-type") == "application/json; charset=utf-8"

    def test_accept_header(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        headers = fake.calls[0]["request"].headers
        assert headers.get("Accept") == "application/json"

    def test_user_agent_header(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        headers = fake.calls[0]["request"].headers
        assert headers.get("User-agent") == "Crypto-AI-Operation-Center/1"

    def test_payload_is_utf8_json(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"text": "acentuación: áéíóú ñ"})
        raw_payload = fake.calls[0]["request"].data
        assert isinstance(raw_payload, bytes)
        decoded = json.loads(raw_payload.decode("utf-8"))
        assert decoded == {"text": "acentuación: áéíóú ñ"}

    def test_timeout_is_passed_to_opener(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=8.25)
        transport.send_payload(payload={"a": 1})
        assert fake.calls[0]["timeout"] == 8.25


class TestAuthorization:
    def test_authorization_header_present_when_secret_configured(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        headers = fake.calls[0]["request"].headers
        assert headers.get("Authorization") == f"Bearer {_FAKE_SECRET}"

    def test_authorization_header_absent_when_no_secret(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(authorization_secret=None), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})
        headers = fake.calls[0]["request"].headers
        assert "Authorization" not in headers

    def test_secret_absent_from_repr(self):
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        assert _FAKE_SECRET not in repr(transport)

    def test_secret_absent_from_errors(self, monkeypatch):
        http_error = urllib.error.HTTPError(url=_FAKE_ENDPOINT_URL, code=401, msg="Unauthorized", hdrs=None, fp=None)
        _install_fake_opener(monkeypatch, raises=http_error)
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        assert _FAKE_SECRET not in str(exc_info.value)


class TestResponseCodes:
    @pytest.mark.parametrize("code", [200, 201, 204, 299])
    def test_success_codes_from_http_error_path_are_treated_as_success(self, monkeypatch, code):
        # urlopen/opener.open() nunca lanza HTTPError para 2xx normalmente,
        # pero el manejador defensivo también debe tratarlo como éxito si
        # alguna vez llegara a recibirlo por esa vía (ver §30, punto 20/21).
        http_error = urllib.error.HTTPError(url=_FAKE_ENDPOINT_URL, code=code, msg="ok", hdrs=None, fp=None)
        _install_fake_opener(monkeypatch, raises=http_error)
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})  # no debe lanzar

    def test_400_raises_transport_error(self, monkeypatch):
        http_error = urllib.error.HTTPError(url=_FAKE_ENDPOINT_URL, code=400, msg="Bad Request", hdrs=None, fp=None)
        _install_fake_opener(monkeypatch, raises=http_error)
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        assert "400" in str(exc_info.value)

    def test_500_raises_transport_error(self, monkeypatch):
        http_error = urllib.error.HTTPError(
            url=_FAKE_ENDPOINT_URL, code=500, msg="Internal Server Error", hdrs=None, fp=None,
        )
        _install_fake_opener(monkeypatch, raises=http_error)
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        assert "500" in str(exc_info.value)

    def test_limited_response_body_is_read(self, monkeypatch):
        _install_fake_opener(monkeypatch, body=b"x" * 10)
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"a": 1})  # no debe lanzar: cuerpo no vacío también es válido


class TestRedirectsRejected:
    """Etapa 6.15 (§30, puntos 22/23): 301/302/303/307/308 deben tratarse
    como fallo, con un mensaje sin `Location`, sin una segunda solicitud."""

    @pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
    def test_redirect_status_raises_controlled_error(self, monkeypatch, code):
        http_error = urllib.error.HTTPError(
            url=_FAKE_ENDPOINT_URL, code=code, msg="redirected",
            hdrs={"Location": "https://evil.example/steal-the-secret"}, fp=None,
        )
        fake = _install_fake_opener(monkeypatch, raises=http_error)
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        message = str(exc_info.value)
        assert "redirects are not allowed" in message.lower()
        assert "Location" not in message
        assert "evil.example" not in message
        assert len(fake.calls) == 1


class TestErrorHandling:
    def test_timeout_raises_transport_error(self, monkeypatch):
        _install_fake_opener(monkeypatch, raises=TimeoutError("timed out"))
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        assert "timeout" in str(exc_info.value).lower()

    def test_url_error_raises_transport_error(self, monkeypatch):
        _install_fake_opener(monkeypatch, raises=urllib.error.URLError("name resolution failed"))
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        assert "network error" in str(exc_info.value).lower()

    def test_ssl_error_raises_transport_error(self, monkeypatch):
        import ssl

        _install_fake_opener(monkeypatch, raises=ssl.SSLError("bad handshake"))
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        assert "tls" in str(exc_info.value).lower()

    def test_unexpected_exception_is_sanitized(self, monkeypatch):
        _install_fake_opener(
            monkeypatch, raises=RuntimeError(f"boom url={_FAKE_ENDPOINT_URL} secret={_FAKE_SECRET}"),
        )
        transport = UrllibWebhookTransport(config=_config(authorization_secret=_FAKE_SECRET), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"a": 1})
        message = str(exc_info.value)
        assert _FAKE_ENDPOINT_URL not in message
        assert _FAKE_SECRET not in message

    def test_never_retries_internally(self, monkeypatch):
        fake = _install_fake_opener(
            monkeypatch, raises=urllib.error.HTTPError(url=_FAKE_ENDPOINT_URL, code=500, msg="err", hdrs=None, fp=None),
        )
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError):
            transport.send_payload(payload={"a": 1})
        assert len(fake.calls) == 1

    def test_non_serializable_payload_raises_transport_error(self, monkeypatch):
        _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"bad": object()})
        assert "serialized" in str(exc_info.value).lower()


class TestPayloadSize:
    """Chequeo defensivo, estructural (§30, punto 17): el transporte no
    trunca -- solo rechaza si el payload que recibe ya excede el límite."""

    def test_payload_under_limit_is_accepted(self, monkeypatch):
        _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        transport.send_payload(payload={"body": "x" * 100})

    def test_payload_at_limit_is_accepted(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        overhead = len(json.dumps({"body": ""}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        body = "x" * (WEBHOOK_MAX_PAYLOAD_BYTES - overhead)
        transport.send_payload(payload={"body": body})
        sent = json.loads(fake.calls[0]["request"].data.decode("utf-8"))
        assert len(fake.calls[0]["request"].data) <= WEBHOOK_MAX_PAYLOAD_BYTES

    def test_payload_over_limit_is_rejected_without_request(self, monkeypatch):
        fake = _install_fake_opener(monkeypatch, body=b"")
        transport = UrllibWebhookTransport(config=_config(), timeout_seconds=5.0)
        body = "x" * (WEBHOOK_MAX_PAYLOAD_BYTES + 1000)
        with pytest.raises(WebhookTransportError) as exc_info:
            transport.send_payload(payload={"body": body})
        assert "maximum allowed size" in str(exc_info.value).lower()
        assert len(fake.calls) == 0

    def test_serialization_is_deterministic(self):
        payload = {"b": 2, "a": 1}
        first = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        second = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        assert first == second == '{"a":1,"b":2}'
