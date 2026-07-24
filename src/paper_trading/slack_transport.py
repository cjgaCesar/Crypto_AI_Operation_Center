"""
Transporte HTTP para el canal de notificaciones de Slack (Etapa 6.13),
segundo canal externo real, construido con el mismo patrón ya aprobado
para Telegram (Etapa 6.12/6.12.1, ver telegram_transport.py):

- `SlackWebhookConfig` (value object inmutable): concentra
  `webhook_url` en un único lugar. Valida esquema HTTPS y host contra
  una lista explícita de hosts de Slack -- nunca acepta "cualquier
  dominio que contenga la palabra slack".
- `SlackTransport` (`Protocol`) / `UrllibSlackTransport`: reciben la
  configuración y el timeout **una sola vez**, en el constructor.
  `send_message()` ya no recibe `webhook_url`/`timeout_seconds` -- solo
  el texto a enviar. `SlackNotificationChannel` (notification_channels.py)
  nunca conoce el webhook, ni siquiera indirectamente.

Solo usa la biblioteca estándar de Python (`urllib.request`,
`urllib.parse`, `json`, `math`, `dataclasses`, `typing`): sin
`requests`/`httpx`/`aiohttp`/`slack_sdk`/`slack-bolt`.

`UrllibSlackTransport` construye un POST JSON (`{"text": ...}`,
`Content-Type: application/json; charset=utf-8`) hacia el Incoming
Webhook configurado, aplica el timeout inyectado, interpreta la
respuesta de texto plano (éxito únicamente si, tras `strip()`, es
exactamente `"ok"`) y convierte cualquier fallo (HTTP, red, timeout,
respuesta distinta de `"ok"`, texto no decodificable, o cualquier
excepción inesperada de una capa inferior) en `SlackTransportError` con
un mensaje sanitizado por categoría -- nunca incluye el webhook, la URL
completa, encabezados ni el cuerpo completo de una respuesta en ningún
mensaje de error.

Nota de seguridad honesta (igual que Telegram, §27.x): esto reduce la
superficie de exposición **accidental** del webhook (no vive en el
Channel, no aparece en `repr`/`str`, no se filtra en errores/logs).
Python no garantiza el borrado físico de un `str` de la memoria del
proceso -- esta capa no afirma ni implica que el secreto "desaparece"
de memoria, solo que se concentra en el único lugar que realmente lo
necesita.

Fuera de alcance (responsabilidad de otras capas): el formato del
mensaje (`notification_channels.py`), reintentos (`AlertDeliveryService`/
`CompositeNotificationChannel`, ver §25.2), persistencia, idempotencia,
y la lectura de variables de entorno (Composition Root/`src/utils/config.py`).
"""

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

_ALLOWED_SLACK_HOSTS = frozenset({"hooks.slack.com", "hooks.slack-gov.com"})


@dataclass(frozen=True)
class SlackWebhookConfig:
    """Value object inmutable con la URL de un Incoming Webhook de Slack.

    `webhook_url` se excluye explícitamente de `repr()`/`str()`
    (`field(repr=False)`) para reducir su exposición accidental en
    logs, tracebacks o depuración interactiva -- mismo criterio que
    `TelegramCredentials` (telegram_transport.py, §27.x).

    Validación estructurada (nunca por red): usa `urllib.parse.urlparse`
    para exigir esquema `https` y un host exactamente igual a uno de
    `hooks.slack.com`/`hooks.slack-gov.com` -- nunca "contiene la
    palabra slack". `urlparse().hostname` ya resuelve correctamente
    intentos de suplantación vía userinfo (`https://hooks.slack.com@evil.com/...`
    -> hostname real `evil.com`, rechazado) y normaliza mayúsculas/
    minúsculas y el puerto.

    Limitación real, no una promesa de seguridad: Python no garantiza
    el borrado seguro de un `str` de la memoria del proceso. Esta clase
    reduce la exposición accidental (dónde aparece el webhook en el
    código/logs/errores), no elimina el secreto de memoria."""

    webhook_url: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.webhook_url, str) or not self.webhook_url.strip():
            raise ValueError("Slack webhook URL is required when Slack notifications are enabled.")

        parsed = urllib.parse.urlparse(self.webhook_url)
        if parsed.scheme != "https":
            raise ValueError("Slack webhook URL must use HTTPS.")
        if parsed.hostname not in _ALLOWED_SLACK_HOSTS:
            raise ValueError("Slack webhook URL must use an approved Slack host.")


class SlackTransportError(Exception):
    """Fallo del transporte de Slack. El mensaje nunca incluye el
    webhook, la URL completa, encabezados ni el cuerpo completo de la
    respuesta."""


class SlackTransport(Protocol):
    def send_message(self, *, text: str) -> None:
        """Envía `text` al Incoming Webhook configurado.

        El webhook y el timeout ya están fijados en el constructor de
        la implementación concreta -- este método recibe únicamente el
        texto. Realiza como máximo una solicitud HTTP por llamada -- no
        reintenta internamente (eso es responsabilidad exclusiva de
        `AlertDeliveryService`/`CompositeNotificationChannel`, ver
        §25.2). Lanza `SlackTransportError` (nunca otro tipo de
        excepción) ante cualquier fallo de red, HTTP, timeout, o una
        respuesta que no sea exactamente `"ok"`."""
        ...


class UrllibSlackTransport:
    """Única implementación real de `SlackTransport`: usa exclusivamente
    `urllib` de la biblioteca estándar.

    Recibe `config`/`timeout_seconds` una sola vez, en el constructor.
    Conserva un único `SlackWebhookConfig` (`self._config`), nunca una
    segunda copia como `self._webhook_url`, para no multiplicar los
    lugares donde el secreto vive en memoria."""

    def __init__(self, *, config: SlackWebhookConfig, timeout_seconds: float = 10.0):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Slack timeout must be a finite number greater than zero.")
        self._config = config
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"UrllibSlackTransport(timeout_seconds={self._timeout_seconds!r})"

    def send_message(self, *, text: str) -> None:
        payload = json.dumps({"text": text}).encode("utf-8")
        request = urllib.request.Request(
            self._config.webhook_url, data=payload, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as exc:
            raise SlackTransportError(f"Slack webhook request failed (HTTP {exc.code}).") from None
        except TimeoutError:
            raise SlackTransportError("Slack webhook request failed (timeout).") from None
        except urllib.error.URLError:
            raise SlackTransportError("Slack webhook request failed (network error).") from None
        except Exception:
            # Sanitización defensiva (igual que Telegram, §27.x): cualquier
            # excepción no anticipada de una capa inferior podría incluir
            # accidentalmente el webhook/la URL completa en su propio
            # str() -- nunca se persiste directamente, se reemplaza
            # siempre por un mensaje genérico sin detalles.
            raise SlackTransportError("Slack webhook request failed (unexpected error).") from None

        try:
            text_body = raw_body.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise SlackTransportError("Slack webhook returned an invalid response.") from None

        if text_body != "ok":
            raise SlackTransportError("Slack webhook returned an unsuccessful response.")
