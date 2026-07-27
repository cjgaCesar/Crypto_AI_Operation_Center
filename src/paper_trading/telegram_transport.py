"""
Transporte HTTP para el canal de notificaciones de Telegram (Etapa 6.12,
endurecido en 6.12.1 -- ver §27.x).

Aísla toda la lógica de red (construir la solicitud, aplicar timeout,
interpretar la respuesta) y las credenciales detrás de dos piezas
pequeñas:

- `TelegramCredentials` (value object inmutable): concentra
  `bot_token`/`chat_id` en un único lugar, en vez de que cada capa
  (Composition Root, canal, transporte) conserve su propia copia.
- `TelegramTransport` (`Protocol`) / `UrllibTelegramTransport`: reciben
  las credenciales y el timeout **una sola vez**, en el constructor.
  `send_message()` ya no recibe `bot_token`/`chat_id`/`timeout_seconds`
  -- solo el texto a enviar. `TelegramNotificationChannel`
  (notification_channels.py) nunca vuelve a conocer ninguna
  credencial, ni siquiera indirectamente.

Solo usa la biblioteca estándar de Python (`urllib.request`,
`urllib.parse`, `json`, `math`): sin `requests`/`httpx`/`aiohttp`/
`telegram`/`python-telegram-bot`/`telebot`.

`UrllibTelegramTransport` construye un POST hacia
`https://api.telegram.org/bot<TOKEN>/sendMessage`, aplica el timeout
inyectado, interpreta el JSON de respuesta y convierte cualquier fallo
(HTTP, red, timeout, JSON inválido, `ok: false`, o cualquier excepción
inesperada de una capa inferior) en `TelegramTransportError` con un
mensaje sanitizado por categoría -- nunca incluye el token, la URL
completa, encabezados, el chat ID ni el cuerpo completo de una
respuesta en ningún mensaje de error.

Nota de seguridad honesta (§27.x): esto reduce la superficie de
exposición **accidental** del token (no vive en el Channel, no aparece
en `repr`/`str`, no se filtra en errores/logs). Python no garantiza el
borrado físico de un `str` de la memoria del proceso -- esta capa no
afirma ni implica que el secreto "desaparece" de memoria, solo que se
concentra en el único lugar que realmente lo necesita.

Fuera de alcance (responsabilidad de otras capas): el formato del
mensaje (`notification_channels.py`), reintentos (`AlertDeliveryService`/
`CompositeNotificationChannel`, ver §25.2), persistencia, idempotencia,
y la lectura de variables de entorno (Composition Root/`src/utils/config.py`).

Etapa 6.16 (§31, auditoría transversal): la validación de
`timeout_seconds` ahora rechaza explícitamente `bool` (`isinstance(...,
bool)`), igual que Slack/Email/Webhook -- corrige una inconsistencia
real detectada en la auditoría: como `bool` es subclase de `int` en
Python, `timeout_seconds=True` pasaba silenciosamente la validación
anterior (`math.isfinite(True) and True > 0`) y se aceptaba como un
timeout válido de 1.0 segundos.
"""

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

_TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass(frozen=True)
class TelegramCredentials:
    """Value object inmutable con las credenciales de un bot de Telegram.

    `bot_token` se excluye explícitamente de `repr()`/`str()`
    (`field(repr=False)`) para reducir su exposición accidental en
    logs, tracebacks o depuración interactiva. No implementa ninguna
    propiedad pública ni método (`bot_token`/`get_token()`) que
    reexponga el secreto más allá de lo que la propia dataclass ya
    conserva como atributo -- solo `UrllibTelegramTransport` accede a
    `credentials.bot_token` directamente, en el único punto donde
    realmente se necesita para construir la URL de la API.

    Limitación real, no una promesa de seguridad: Python no garantiza
    el borrado seguro de un `str` de la memoria del proceso. Esta clase
    reduce la exposición accidental (dónde aparece el token en el
    código/logs/errores), no elimina el secreto de memoria."""

    bot_token: str = field(repr=False)
    chat_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.bot_token, str) or not self.bot_token.strip():
            raise ValueError("Telegram bot token is required when Telegram notifications are enabled.")
        if not isinstance(self.chat_id, str) or not self.chat_id.strip():
            raise ValueError("Telegram chat ID is required when Telegram notifications are enabled.")


class TelegramTransportError(Exception):
    """Fallo del transporte de Telegram. El mensaje nunca incluye el
    token, la URL completa, el chat ID, encabezados ni el cuerpo
    completo de la respuesta (§27/§27.x)."""


class TelegramTransport(Protocol):
    def send_message(self, *, text: str) -> None:
        """Envía `text` al chat configurado, vía el bot configurado.

        Las credenciales y el timeout ya están fijados en el
        constructor de la implementación concreta -- este método
        recibe únicamente el texto. Realiza como máximo una solicitud
        HTTP por llamada -- no reintenta internamente (eso es
        responsabilidad exclusiva de `AlertDeliveryService`/
        `CompositeNotificationChannel`, ver §25.2). Lanza
        `TelegramTransportError` (nunca otro tipo de excepción) ante
        cualquier fallo de red, HTTP, timeout, JSON inválido o una
        respuesta sin `{"ok": true}`."""
        ...


class UrllibTelegramTransport:
    """Única implementación real de `TelegramTransport`: usa
    exclusivamente `urllib` de la biblioteca estándar.

    Recibe `credentials`/`timeout_seconds` una sola vez, en el
    constructor -- nunca en `send_message()`. Conserva un único
    `TelegramCredentials` (`self._credentials`), nunca una segunda
    copia como `self._bot_token`/`self._chat_id`, para no multiplicar
    los lugares donde el secreto vive en memoria."""

    def __init__(self, *, credentials: TelegramCredentials, timeout_seconds: float = 10.0):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Telegram timeout must be a finite number greater than zero.")
        self._credentials = credentials
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"UrllibTelegramTransport(timeout_seconds={self._timeout_seconds!r})"

    def send_message(self, *, text: str) -> None:
        url = f"{_TELEGRAM_API_BASE}/bot{self._credentials.bot_token}/sendMessage"
        payload = urllib.parse.urlencode(
            {"chat_id": self._credentials.chat_id, "text": text}
        ).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as exc:
            raise TelegramTransportError(f"Telegram API request failed (HTTP {exc.code}).") from None
        except TimeoutError:
            raise TelegramTransportError("Telegram API request failed (timeout).") from None
        except urllib.error.URLError:
            raise TelegramTransportError("Telegram API request failed (network error).") from None
        except Exception:
            # Sanitización defensiva (§27.x): cualquier excepción no
            # anticipada de una capa inferior podría incluir
            # accidentalmente el token/la URL completa/el chat ID en su
            # propio str() -- nunca se persiste directamente, se
            # reemplaza siempre por un mensaje genérico sin detalles.
            raise TelegramTransportError("Telegram API request failed (unexpected error).") from None

        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            raise TelegramTransportError("Telegram API returned invalid JSON.") from None

        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramTransportError("Telegram API returned an unsuccessful response.")
