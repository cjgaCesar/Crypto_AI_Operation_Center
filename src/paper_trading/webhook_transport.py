"""
Transporte HTTP para el canal de notificaciones de Webhook genérico
(Etapa 6.15), cuarto y último canal externo real, construido con el
mismo patrón ya aprobado para Telegram/Slack/Email (Etapas 6.12-6.14,
ver telegram_transport.py/slack_transport.py/email_transport.py):

- `WebhookEndpointConfig` (value object inmutable): concentra
  `endpoint_url`/`authorization_secret` en un único lugar. Valida
  esquema HTTPS, ausencia de userinfo/query/fragment, puerto por
  defecto (443 o ninguno), un path no-raíz sin segmentos ambiguos, y
  -- a diferencia de Telegram/Slack, que apuntan a un servicio fijo
  conocido -- una protección mínima contra SSRF, ya que este webhook es
  genérico y el usuario controla completamente el destino.
- `WebhookTransport` (`Protocol`) / `UrllibWebhookTransport`: reciben la
  configuración y el timeout **una sola vez**, en el constructor.
  `send_payload()` ya no recibe `endpoint_url`/`authorization_secret`/
  `timeout_seconds` -- solo el payload ya construido.
  `WebhookNotificationChannel` (notification_channels.py) nunca conoce
  el endpoint ni el secreto, ni siquiera indirectamente.

Solo usa la biblioteca estándar de Python (`json`, `math`, `ssl`,
`urllib.error`, `urllib.parse`, `urllib.request`, `dataclasses`,
`typing`, `ipaddress`): sin `requests`/`httpx`/`aiohttp`/`webhooks`/
`fastapi`/`flask`.

`UrllibWebhookTransport` construye un POST JSON hacia el endpoint
configurado, aplica el timeout inyectado, usa un contexto TLS seguro
(`ssl.create_default_context()`, nunca `_create_unverified_context()`),
**nunca sigue redirecciones** (301/302/303/307/308 se tratan como
fallo, nunca como una segunda solicitud), y convierte cualquier fallo
(HTTP, red, timeout, TLS, serialización, redirección, o cualquier
excepción inesperada de una capa inferior) en `WebhookTransportError`
con un mensaje sanitizado por categoría -- nunca incluye el endpoint,
el secreto de autorización, encabezados, el payload completo ni el
cuerpo completo de una respuesta en ningún mensaje de error.

Nota de seguridad honesta (igual que Telegram/Slack/Email): esto
reduce la superficie de exposición **accidental** del secreto (no vive
en el Channel, no aparece en `repr`/`str`, no se filtra en
errores/logs). Python no garantiza el borrado físico de un `str` de la
memoria del proceso -- esta capa no afirma ni implica que el secreto
"desaparece" de memoria, solo que se concentra en el único lugar que
realmente lo necesita.

Limitación real de la protección SSRF (documentada, no oculta): la
validación es puramente estructural, sobre el literal de la URL, y
nunca realiza una resolución DNS durante la construcción de la
configuración (`no realizar resolución DNS durante la validación`, ver
§30). Esto significa que un nombre de dominio que hoy resuelve a una
IP pública podría, en el futuro, resolver a una IP privada/interna
("DNS rebinding") sin que esta validación lo detecte -- la protección
cubre IPs literales en la URL y algunos nombres reservados conocidos
(`localhost`/`*.localhost`), no el universo completo de ataques SSRF
basados en DNS.

Fuera de alcance (responsabilidad de otras capas): la construcción del
payload (`notification_channels.py`, `_build_webhook_payload()`),
reintentos (`AlertDeliveryService`/`CompositeNotificationChannel`, ver
§25.2), persistencia, idempotencia, y la lectura de variables de
entorno (Composition Root/`src/utils/config.py`).
"""

import ipaddress
import json
import math
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Protocol

WEBHOOK_MAX_PAYLOAD_BYTES = 65536

_MAX_RESPONSE_BYTES = 4096
_ALLOWED_PORTS = (None, 443)
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_INVALID_ADDRESS_MESSAGE = "Webhook endpoint URL must not target a local or internal host."
_INVALID_PATH_MESSAGE = "Webhook endpoint URL must include a valid non-root path."
_INVALID_AUTHORIZATION_MESSAGE = (
    "Webhook authorization secret must be a non-empty value without a Bearer prefix or line breaks."
)


def _validate_webhook_host(hostname: Optional[str]) -> None:
    """Protección mínima contra SSRF (§30, Etapa 6.15, punto 9): rechaza
    hosts locales/internos conocidos y cualquier IP literal privada,
    loopback, link-local, multicast, reservada o no especificada.
    Nunca resuelve DNS -- un nombre público que hoy resuelve a una IP
    pública se acepta aquí, sin garantía sobre el futuro (DNS
    rebinding, ver docstring del módulo)."""
    if not hostname:
        raise ValueError("Webhook endpoint URL must include a host.")

    lowered = hostname.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        raise ValueError(_INVALID_ADDRESS_MESSAGE)

    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return  # No es una IP literal: nombre DNS, sin resolución aquí.

    if (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    ):
        raise ValueError(_INVALID_ADDRESS_MESSAGE)


def _validate_webhook_path(path: str) -> None:
    """Exige un path no-raíz (§30, punto 11): debe existir, empezar con
    `/`, y ningún segmento puede estar vacío, ser `.`/`..`, ni -- tras
    `urllib.parse.unquote` -- decodificar a `.`/`..` o contener `/`
    (rutas codificadas ambiguas nunca se normalizan en silencio). A
    diferencia de Slack (§28.x), no exige una cantidad ni estructura
    fija de segmentos: este webhook es genérico."""
    if not path or path == "/":
        raise ValueError(_INVALID_PATH_MESSAGE)

    segments = path.split("/")
    if segments[0] != "":
        raise ValueError(_INVALID_PATH_MESSAGE)

    non_empty_segments = segments[1:]
    if any(not segment for segment in non_empty_segments):
        raise ValueError(_INVALID_PATH_MESSAGE)
    if any(segment in {".", ".."} for segment in non_empty_segments):
        raise ValueError(_INVALID_PATH_MESSAGE)

    decoded_segments = [urllib.parse.unquote(segment) for segment in non_empty_segments]
    if any(segment in {".", ".."} for segment in decoded_segments):
        raise ValueError(_INVALID_PATH_MESSAGE)
    if any("/" in segment for segment in decoded_segments):
        raise ValueError(_INVALID_PATH_MESSAGE)


def _validate_authorization_secret(secret: str) -> None:
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError(_INVALID_AUTHORIZATION_MESSAGE)
    if "\r" in secret or "\n" in secret:
        raise ValueError(_INVALID_AUTHORIZATION_MESSAGE)
    if secret.strip().lower().startswith("bearer"):
        raise ValueError(_INVALID_AUTHORIZATION_MESSAGE)


@dataclass(frozen=True)
class WebhookEndpointConfig:
    """Value object inmutable con el endpoint y el secreto opcional de
    un webhook HTTP genérico.

    `endpoint_url`/`authorization_secret` se excluyen explícitamente de
    `repr()`/`str()` (`field(repr=False)`) para reducir su exposición
    accidental en logs, tracebacks o depuración interactiva -- mismo
    criterio que `TelegramCredentials`/`SlackWebhookConfig`/
    `SmtpEmailConfig`.

    Validación estructural (nunca por red ni DNS), en orden
    determinista: tipo/no vacío -> esquema HTTPS -> host presente ->
    userinfo ausente -> query ausente -> fragment ausente -> puerto
    (`None`/`443`) -> host no local/interno (SSRF, ver
    `_validate_webhook_host`) -> path no-raíz válido (ver
    `_validate_webhook_path`) -> secreto de autorización (si está
    presente, ver `_validate_authorization_secret`).

    Limitación real, no una promesa de seguridad: Python no garantiza
    el borrado seguro de un `str` de la memoria del proceso. Esta clase
    reduce la exposición accidental (dónde aparecen el endpoint/secreto
    en el código/logs/errores), no elimina el secreto de memoria."""

    endpoint_url: str = field(repr=False)
    authorization_secret: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint_url, str) or not self.endpoint_url.strip():
            raise ValueError("Webhook endpoint URL is required when Webhook notifications are enabled.")

        parsed = urllib.parse.urlparse(self.endpoint_url)

        if parsed.scheme != "https":
            raise ValueError("Webhook endpoint URL must use HTTPS.")

        if not parsed.hostname:
            raise ValueError("Webhook endpoint URL must include a host.")

        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Webhook endpoint URL must not include user information.")

        if parsed.query != "":
            raise ValueError("Webhook endpoint URL must not include a query string.")

        if parsed.fragment != "":
            raise ValueError("Webhook endpoint URL must not include a fragment.")

        try:
            port = parsed.port
        except ValueError:
            raise ValueError("Webhook endpoint URL contains an invalid port.") from None
        if port not in _ALLOWED_PORTS:
            raise ValueError("Webhook endpoint URL must use the default HTTPS port.")

        _validate_webhook_host(parsed.hostname)
        _validate_webhook_path(parsed.path)

        if self.authorization_secret is not None:
            _validate_authorization_secret(self.authorization_secret)


class WebhookTransportError(Exception):
    """Fallo del transporte de Webhook. El mensaje nunca incluye el
    endpoint, el secreto de autorización, encabezados, el payload
    completo ni el cuerpo completo de la respuesta."""


class WebhookTransport(Protocol):
    def send_payload(self, *, payload: dict) -> None:
        """Envía `payload` (ya serializable a JSON) al endpoint
        configurado.

        El endpoint, el secreto de autorización y el timeout ya están
        fijados en el constructor de la implementación concreta --
        este método recibe únicamente el payload. Realiza como máximo
        una solicitud HTTP por llamada -- no reintenta internamente
        (eso es responsabilidad exclusiva de `AlertDeliveryService`/
        `CompositeNotificationChannel`, ver §25.2) y nunca sigue
        redirecciones. Lanza `WebhookTransportError` (nunca otro tipo
        de excepción) ante cualquier fallo de red, HTTP, TLS, timeout,
        redirección o serialización."""
        ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Bloquea toda redirección (§30, punto 22): seguirla podría enviar
    el secreto de autorización a otro host, eludir la protección SSRF,
    o cambiar de HTTPS a otro esquema. `redirect_request()` es el punto
    de extensión documentado por `urllib` para abortar una redirección
    -- lanzar `HTTPError` aquí hace que `urlopen()` la propague como
    cualquier otro error HTTP, con el mismo código de estado original."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


class UrllibWebhookTransport:
    """Única implementación real de `WebhookTransport`: usa
    exclusivamente `urllib`/`ssl` de la biblioteca estándar.

    Recibe `config`/`timeout_seconds` una sola vez, en el constructor.
    Conserva un único `WebhookEndpointConfig` (`self._config`), nunca
    copias sueltas como `self._endpoint_url`/`self._authorization_secret`,
    para no multiplicar los lugares donde el secreto vive en memoria."""

    def __init__(self, *, config: WebhookEndpointConfig, timeout_seconds: float = 10.0):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Webhook timeout must be a finite number greater than zero.")
        self._config = config
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"UrllibWebhookTransport(timeout_seconds={self._timeout_seconds!r})"

    def send_payload(self, *, payload: dict) -> None:
        try:
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            raise WebhookTransportError("Webhook payload could not be serialized.") from None

        encoded = serialized.encode("utf-8")
        if len(encoded) > WEBHOOK_MAX_PAYLOAD_BYTES:
            raise WebhookTransportError("Webhook payload exceeds the maximum allowed size.")

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "Crypto-AI-Operation-Center/1",
        }
        if self._config.authorization_secret is not None:
            headers["Authorization"] = f"Bearer {self._config.authorization_secret}"

        request = urllib.request.Request(
            self._config.endpoint_url, data=encoded, method="POST", headers=headers,
        )
        opener = urllib.request.build_opener(
            _NoRedirectHandler(), urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

        try:
            with opener.open(request, timeout=self._timeout_seconds) as response:
                response.read(_MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            if exc.code in _REDIRECT_STATUS_CODES:
                raise WebhookTransportError("Webhook redirects are not allowed.") from None
            if 200 <= exc.code <= 299:
                return
            raise WebhookTransportError(f"Webhook request failed (HTTP {exc.code}).") from None
        except TimeoutError:
            raise WebhookTransportError("Webhook request failed (timeout).") from None
        except ssl.SSLError:
            raise WebhookTransportError("Webhook TLS validation failed.") from None
        except urllib.error.URLError:
            raise WebhookTransportError("Webhook request failed (network error).") from None
        except Exception:
            # Sanitización defensiva (igual que Telegram/Slack/Email): cualquier
            # excepción no anticipada de una capa inferior podría incluir
            # accidentalmente el endpoint/el secreto en su propio str() --
            # nunca se persiste directamente, se reemplaza siempre por un
            # mensaje genérico sin detalles.
            raise WebhookTransportError("Webhook request failed unexpectedly.") from None
