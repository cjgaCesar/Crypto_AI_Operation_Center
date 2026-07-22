"""
Transporte HTTP para el canal de notificaciones de Telegram (Etapa 6.12).

Aísla toda la lógica de red (construir la solicitud, aplicar timeout,
interpretar la respuesta) detrás de un `Protocol` pequeño
(`TelegramTransport`), para que `TelegramNotificationChannel`
(notification_channels.py) nunca conozca `urllib`/JSON/el endpoint
oficial de Telegram directamente -- solo invoca
`transport.send_message(...)`.

Solo usa la biblioteca estándar de Python (`urllib.request`,
`urllib.parse`, `json`): sin `requests`/`httpx`/`aiohttp`/`telegram`/
`python-telegram-bot`/`telebot`.

`UrllibTelegramTransport` construye un POST hacia
`https://api.telegram.org/bot<TOKEN>/sendMessage`, aplica
`timeout_seconds`, interpreta el JSON de respuesta y convierte
cualquier fallo (HTTP, red, timeout, JSON inválido, `ok: false`) en
`TelegramTransportError` con un mensaje sanitizado -- nunca incluye el
token, la URL completa, encabezados ni el cuerpo completo de la
respuesta en ningún mensaje de error.

Fuera de alcance (responsabilidad de otras capas): el formato del
mensaje (`notification_channels.py`), reintentos (`AlertDeliveryService`/
`CompositeNotificationChannel`, ver §25.2), persistencia, idempotencia,
y la lectura de variables de entorno (Composition Root/`src/utils/config.py`).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

_TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramTransportError(Exception):
    """Fallo del transporte de Telegram. El mensaje nunca incluye el
    token, la URL completa, encabezados ni el cuerpo completo de la
    respuesta (§27)."""


class TelegramTransport(Protocol):
    def send_message(
        self,
        *,
        bot_token: str,
        chat_id: str,
        text: str,
        timeout_seconds: float,
    ) -> None:
        """Envía `text` al chat `chat_id` vía el bot `bot_token`.

        Realiza como máximo una solicitud HTTP por llamada -- no
        reintenta internamente (eso es responsabilidad exclusiva de
        `AlertDeliveryService`/`CompositeNotificationChannel`, ver
        §25.2). Lanza `TelegramTransportError` (nunca otro tipo de
        excepción) ante cualquier fallo de red, HTTP, timeout, JSON
        inválido o una respuesta sin `{"ok": true}`."""
        ...


class UrllibTelegramTransport:
    """Única implementación real de `TelegramTransport`: usa
    exclusivamente `urllib` de la biblioteca estándar."""

    def send_message(
        self,
        *,
        bot_token: str,
        chat_id: str,
        text: str,
        timeout_seconds: float,
    ) -> None:
        url = f"{_TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as exc:
            raise TelegramTransportError(f"Telegram API request failed (HTTP {exc.code}).") from None
        except TimeoutError:
            raise TelegramTransportError("Telegram API request failed (timeout).") from None
        except urllib.error.URLError as exc:
            raise TelegramTransportError(
                f"Telegram API request failed (network error: {type(exc.reason).__name__})."
            ) from None

        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            raise TelegramTransportError("Telegram API returned invalid JSON.") from None

        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramTransportError("Telegram API returned an unsuccessful response.")
