"""
Canales de entrega de alertas de inspección -- patrón Strategy (Etapa 6.10,
ampliado en 6.10.1 con idempotencia de entrega por canal, §25.2, y en
6.11 para transportar NotificationMessage en vez de InspectionAlert, §26).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §24/§25/§26. `InspectionNotificationChannel`
es la única abstracción que `AlertDeliveryService` conoce: nunca un
`if`/`isinstance`/switch por tipo de canal, ni aquí ni allá. Agregar un
canal real en el futuro (Slack, Email, Telegram, Webhook) significa
únicamente reemplazar el cuerpo de `deliver()` del placeholder
correspondiente -- nunca tocar `AlertDeliveryService` ni
`CompositeNotificationChannel`.

`LoggingNotificationChannel`/`NullNotificationChannel` son exactamente
la misma implementación que `LoggingInspectionAlertSink`/
`NullInspectionAlertSink` (Etapa 6.9, ver alert_sink.py, que ahora las
reexporta como alias por compatibilidad hacia atrás).

Desde la Etapa 6.15 (§30) ya no queda ningún placeholder en esta lista:
`EmailNotificationChannel`/`SlackNotificationChannel`/
`TelegramNotificationChannel`/`WebhookNotificationChannel` son los
cuatro canales externos reales (Etapas 6.12-6.15), además de
`LoggingNotificationChannel`/`NullNotificationChannel`.

Etapa 6.12 (§27): `TelegramNotificationChannel` deja de ser un
placeholder. Es un canal real que transporta un `NotificationMessage`
ya renderizado vía la API de Telegram, a través de un
`TelegramTransport` inyectado (telegram_transport.py, único módulo que
conoce `urllib`/el endpoint HTTP oficial). Nunca conoce
`InspectionAlert`, nunca accede al repositorio, nunca decide
reintentos (eso sigue siendo exclusivo de `AlertDeliveryService`/
`CompositeNotificationChannel`) -- `deliver()` realiza como máximo una
solicitud HTTP por llamada.

Etapa 6.12.1 (§27.x): `TelegramNotificationChannel` deja de conocer
`bot_token`/`chat_id`/`timeout_seconds` por completo -- esas
credenciales quedan encapsuladas exclusivamente en el
`TelegramTransport` ya configurado (`telegram_transport.py`), inyectado
por la Composition Root. El canal solo conoce `transport`/`clock`, y
`transport.send_message()` recibe únicamente el texto ya formateado.

Etapa 6.13 (§28): `SlackNotificationChannel` deja de ser un placeholder,
con el mismo patrón que Telegram: recibe un `SlackTransport` ya
configurado (slack_transport.py, único módulo que conoce `urllib`/el
Incoming Webhook), nunca el webhook. `_format_slack_text()` neutraliza
menciones globales (`@channel`/`@here`/`@everyone`/`<!channel>`/
`<!here>`/`<!everyone>`) antes de truncar a `SLACK_MAX_MESSAGE_LENGTH`.

Etapa 6.14 (§29): `EmailNotificationChannel` deja de ser un placeholder,
mismo patrón: recibe un `EmailTransport` ya configurado
(email_transport.py, único módulo que conoce `smtplib`/`ssl`), nunca
host/puerto/credenciales/remitente/destinatario. `_format_email_subject()`/
`_format_email_body()` neutralizan CR/LF/tabs (defensa en profundidad
contra header injection) antes de truncar a
`EMAIL_MAX_SUBJECT_LENGTH`/`EMAIL_MAX_BODY_LENGTH`.

Etapa 6.10.1 (§25.2): `CompositeNotificationChannel` deja de llevar la
lógica de reintentos únicamente en memoria. Ahora recibe `repository` y
`max_attempts`, y consulta/persiste `InspectionAlertChannelDelivery`
(alert_id + channel_name) antes y después de invocar cada canal -- un
canal ya `DELIVERED` nunca se vuelve a invocar, y ese estado sobrevive
reinicios, nuevas instancias y reconstrucciones de la Composition Root.

Etapa 6.11 (§26): ningún canal (ni `deliver()` de esta lista, ni el
Protocol) vuelve a conocer `InspectionAlert`. Reciben `NotificationMessage`
(notification_templates.py), ya renderizado por
`InspectionNotificationTemplate` -- separación completa de "qué se
comunica" (plantilla) de "cómo se comunica" (canal).
`CompositeNotificationChannel` recupera el `alert_id` que necesita para
su idempotencia por canal desde `message.alert_id`, nunca de un objeto
`InspectionAlert` directo.

Etapa 6.11.1 (§26.x): `alert_id` pasa a ser un campo explícito de
`NotificationMessage` (antes vivía en `metadata["alert_id"]`, sin
validación). `AlertDeliveryService` ahora valida el resultado de la
plantilla (tipo correcto y `alert_id` coincidente con la alerta real)
antes de invocar cualquier canal -- ningún canal de esta lista se
invoca jamás con un `NotificationMessage` inválido o con un `alert_id`
que no corresponda a la alerta que se está entregando.

Etapa 6.15 (§30): `WebhookNotificationChannel` deja de ser un
placeholder -- era el último. Mismo patrón que Telegram/Slack/Email:
recibe un `WebhookTransport` ya configurado (webhook_transport.py,
único módulo que conoce `urllib`/`ssl`/el endpoint HTTPS), nunca el
endpoint ni el secreto de autorización. A diferencia de los otros tres
canales (que envían texto), Webhook envía un payload JSON estructurado
-- `_build_webhook_payload()` es la función pura que lo construye a
partir de un `NotificationMessage`, incluyendo su propia lógica de
truncado UTF-8-seguro del cuerpo para respetar
`WEBHOOK_MAX_PAYLOAD_BYTES` (definida en webhook_transport.py, única
fuente de verdad, importada aquí). Con este canal ya real, no queda
ningún placeholder dentro de `inspection_notifications`.
"""

import json
import logging
from typing import Optional, Protocol

from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus, InspectionAlertChannelDelivery
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.notification_templates import NotificationMessage
from src.paper_trading.email_transport import EmailTransport
from src.paper_trading.runtime import Clock, SystemClock
from src.paper_trading.slack_transport import SlackTransport
from src.paper_trading.telegram_transport import TelegramTransport
from src.paper_trading.webhook_transport import WEBHOOK_MAX_PAYLOAD_BYTES, WebhookTransport, WebhookTransportError

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_TELEGRAM_TRUNCATION_MARK = "\n[Mensaje truncado]"

SLACK_MAX_MESSAGE_LENGTH = 4000
_SLACK_TRUNCATION_MARK = "\n[Mensaje truncado]"
_SLACK_MENTION_PATTERNS = ("@channel", "@here", "@everyone", "<!channel>", "<!here>", "<!everyone>")

EMAIL_MAX_SUBJECT_LENGTH = 180
_EMAIL_SUBJECT_TRUNCATION_MARK = "…"
EMAIL_MAX_BODY_LENGTH = 10000
_EMAIL_BODY_TRUNCATION_MARK = "\n[Mensaje truncado]"

_WEBHOOK_BODY_TRUNCATION_MARK = "\n[Mensaje truncado]"


class InspectionNotificationChannel(Protocol):
    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        """Entrega `message`. Nunca lanza: captura sus propios errores y los
        refleja en el AlertDeliveryResult devuelto."""
        ...


class LoggingNotificationChannel:
    """Entrega real: escribe la alerta vía `logging` (nunca `print`).

    El nivel de log depende de la severidad de la alerta (CRITICAL/ERROR
    -> logger.error, WARNING -> logger.warning, resto -> logger.info).
    Captura cualquier excepción del propio logging (ej. un handler mal
    configurado) y la refleja como una entrega fallida, en vez de dejarla
    propagar -- AlertDeliveryService/CompositeNotificationChannel dependen
    de que deliver() nunca lance.

    Recibe un `Clock` inyectado (nunca `datetime.now()` directo, ver
    Paso 4 de la Etapa 6.9, principio 14): `delivered_at` es
    responsabilidad del canal, ya que forma parte del
    `AlertDeliveryResult` que este produce.
    """

    def __init__(self, clock: Clock = SystemClock()):
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        try:
            if message.severity is not None and message.severity.value in ("CRITICAL", "ERROR"):
                logger.error("%s -- %s", message.title, message.body)
            elif message.severity is not None and message.severity.value == "WARNING":
                logger.warning("%s -- %s", message.title, message.body)
            else:
                logger.info("%s -- %s", message.title, message.body)
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
        except Exception as exc:
            return AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=self._clock.now())


class NullNotificationChannel:
    """No hace nada: ignora el mensaje recibido y siempre reporta éxito.
    Solo para pruebas."""

    def __init__(self, clock: Clock = SystemClock()):
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())


def _sanitize_email_header_value(value: str) -> str:
    """Defensa en profundidad contra header injection (§29.x): aunque
    `NotificationMessage` ya pasó por el Template (nunca debería traer
    CR/LF), esta función igual reemplaza CR/LF/tabs por espacios y
    colapsa espacios repetidos antes de usar el valor como cabecera
    SMTP -- nunca permite que un salto de línea cree una cabecera
    nueva (ej. `"Bcc: ..."`)."""
    sanitized = value.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(sanitized.split())


def _format_email_subject(message: NotificationMessage) -> str:
    """Adapta un NotificationMessage ya renderizado al asunto de un
    email (§29). Pura y determinista: nunca incluye `alert_id` ni
    metadata completa. Trunca de forma controlada si el resultado
    supera `EMAIL_MAX_SUBJECT_LENGTH`, marcando el corte con
    `_EMAIL_SUBJECT_TRUNCATION_MARK`."""
    subject = _sanitize_email_header_value(f"[Crypto AI] {message.title}")
    if len(subject) <= EMAIL_MAX_SUBJECT_LENGTH:
        return subject

    truncated_length = EMAIL_MAX_SUBJECT_LENGTH - len(_EMAIL_SUBJECT_TRUNCATION_MARK)
    return subject[:truncated_length] + _EMAIL_SUBJECT_TRUNCATION_MARK


def _format_email_body(message: NotificationMessage) -> str:
    """Adapta un NotificationMessage ya renderizado al cuerpo de texto
    plano de un email (§29). Pura y determinista: nunca HTML, nunca
    incluye metadata completa ni `alert_id` (mismo criterio que
    Telegram/Slack, §27/§28). Trunca de forma controlada si el
    resultado supera `EMAIL_MAX_BODY_LENGTH`, marcando el corte con
    `_EMAIL_BODY_TRUNCATION_MARK`; nunca divide en varios emails."""
    lines = [message.title, "", message.body]
    if message.severity is not None:
        lines.append("")
        lines.append(f"Severidad: {message.severity.value}")
    text = "\n".join(lines)

    if len(text) <= EMAIL_MAX_BODY_LENGTH:
        return text

    truncated_length = EMAIL_MAX_BODY_LENGTH - len(_EMAIL_BODY_TRUNCATION_MARK)
    return text[:truncated_length] + _EMAIL_BODY_TRUNCATION_MARK


class EmailNotificationChannel:
    """Canal real (Etapa 6.14, §29): entrega vía SMTP, a través de un
    `EmailTransport` inyectado y ya configurado (email_transport.py) --
    mismo patrón que `TelegramNotificationChannel`/`SlackNotificationChannel`
    (§27/§27.x/§28).

    Nunca conoce `InspectionAlert` (solo `NotificationMessage`, igual
    que el resto de los canales), nunca accede al repositorio, nunca
    persiste estado directamente, y nunca decide reintentos globales ni
    por canal -- eso es responsabilidad exclusiva de
    `AlertDeliveryService`/`CompositeNotificationChannel` (§25.2).
    `deliver()` realiza como máximo UNA sesión SMTP por llamada: no
    reintenta internamente.

    No conoce ni almacena host/puerto/username/password/sender/
    recipient/security/timeout -- esa configuración queda encapsulada
    exclusivamente en el `transport` ya construido por la Composition
    Root (ver `SmtpEmailConfig`/`SmtpEmailTransport`). Los únicos
    atributos propios de este canal son `transport`/`clock`.
    """

    def __init__(
        self,
        *,
        transport: EmailTransport,
        clock: Clock = SystemClock(),
    ):
        self._transport = transport
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        subject = _format_email_subject(message)
        body = _format_email_body(message)
        try:
            self._transport.send_message(subject=subject, body=body)
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
        except Exception as exc:
            return AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=self._clock.now())


def _neutralize_slack_mentions(text: str) -> str:
    """Inserta un carácter de ancho cero (U+200B) inmediatamente después
    del signo de apertura de cada patrón de mención global de Slack
    (`@channel`/`@here`/`@everyone`/`<!channel>`/`<!here>`/`<!everyone>`),
    para que Slack nunca los reconozca como menciones reales -- el texto
    sigue siendo legible para una persona (el carácter es invisible en
    la práctica), pero deja de coincidir con el patrón exacto que Slack
    interpreta como mención global."""
    neutralized = text
    for pattern in _SLACK_MENTION_PATTERNS:
        if pattern.startswith("<!"):
            replacement = "<!​" + pattern[2:]
        else:
            replacement = "@​" + pattern[1:]
        neutralized = neutralized.replace(pattern, replacement)
    return neutralized


def _format_slack_text(message: NotificationMessage) -> str:
    """Adapta un NotificationMessage ya renderizado al texto plano que
    Slack transporta (§28). Pura y determinista: nunca Block Kit, nunca
    `mrkdwn` específico de Slack, nunca incluye metadata completa ni
    `alert_id` (mismo criterio que Telegram, §27). Neutraliza menciones
    globales (ver `_neutralize_slack_mentions`) antes de truncar de
    forma controlada si el resultado supera `SLACK_MAX_MESSAGE_LENGTH`,
    marcando el corte con `_SLACK_TRUNCATION_MARK`; nunca divide en
    varios mensajes."""
    lines = [message.title, "", message.body]
    if message.severity is not None:
        lines.append("")
        lines.append(f"Severidad: {message.severity.value}")
    text = _neutralize_slack_mentions("\n".join(lines))

    if len(text) <= SLACK_MAX_MESSAGE_LENGTH:
        return text

    truncated_length = SLACK_MAX_MESSAGE_LENGTH - len(_SLACK_TRUNCATION_MARK)
    return text[:truncated_length] + _SLACK_TRUNCATION_MARK


class SlackNotificationChannel:
    """Canal real (Etapa 6.13, §28): entrega vía un Incoming Webhook de
    Slack, a través de un `SlackTransport` inyectado y ya configurado
    (slack_transport.py) -- mismo patrón que `TelegramNotificationChannel`
    (§27/§27.x).

    Nunca conoce `InspectionAlert` (solo `NotificationMessage`, igual
    que el resto de los canales), nunca accede al repositorio, nunca
    persiste estado directamente, y nunca decide reintentos globales ni
    por canal -- eso es responsabilidad exclusiva de
    `AlertDeliveryService`/`CompositeNotificationChannel` (§25.2).
    `deliver()` realiza como máximo UNA solicitud HTTP por llamada: no
    reintenta internamente.

    No conoce ni almacena el webhook ni ningún timeout -- esa
    configuración queda encapsulada exclusivamente en el `transport` ya
    construido por la Composition Root (ver `SlackWebhookConfig`/
    `UrllibSlackTransport`). Los únicos atributos propios de este canal
    son `transport`/`clock`.
    """

    def __init__(
        self,
        *,
        transport: SlackTransport,
        clock: Clock = SystemClock(),
    ):
        self._transport = transport
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        text = _format_slack_text(message)
        try:
            self._transport.send_message(text=text)
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
        except Exception as exc:
            return AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=self._clock.now())


def _format_telegram_text(message: NotificationMessage) -> str:
    """Adapta un NotificationMessage ya renderizado al texto plano que
    Telegram transporta (§27). Pura y determinista: nunca HTML, nunca
    Markdown específico de Telegram, nunca incluye metadata completa ni
    `alert_id` (decisión explícita, ver §27 -- el texto es solo para
    lectura humana, no para correlación). Trunca de forma controlada si
    el resultado supera TELEGRAM_MAX_MESSAGE_LENGTH, marcando el corte
    con `_TELEGRAM_TRUNCATION_MARK`; nunca divide en varios mensajes."""
    lines = [message.title, "", message.body]
    if message.severity is not None:
        lines.append("")
        lines.append(f"Severidad: {message.severity.value}")
    text = "\n".join(lines)

    if len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        return text

    truncated_length = TELEGRAM_MAX_MESSAGE_LENGTH - len(_TELEGRAM_TRUNCATION_MARK)
    return text[:truncated_length] + _TELEGRAM_TRUNCATION_MARK


class TelegramNotificationChannel:
    """Canal real (Etapa 6.12, §27; endurecido en 6.12.1, §27.x): entrega
    vía la API de Telegram a través de un `TelegramTransport` inyectado
    y ya configurado (telegram_transport.py).

    Nunca conoce `InspectionAlert` (solo `NotificationMessage`, igual
    que el resto de los canales), nunca accede al repositorio, nunca
    persiste estado directamente, y nunca decide reintentos globales ni
    por canal -- eso es responsabilidad exclusiva de
    `AlertDeliveryService`/`CompositeNotificationChannel` (§25.2).
    `deliver()` realiza como máximo UNA solicitud HTTP por llamada: no
    reintenta internamente.

    Desde la Etapa 6.12.1, no conoce ni almacena `bot_token`/`chat_id`/
    `timeout_seconds` -- esas credenciales quedan encapsuladas
    exclusivamente en el `transport` ya construido por la Composition
    Root (ver `TelegramCredentials`/`UrllibTelegramTransport`). El único
    atributo propio de este canal, además de `transport`, es `clock`.
    """

    def __init__(
        self,
        *,
        transport: TelegramTransport,
        clock: Clock = SystemClock(),
    ):
        self._transport = transport
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        text = _format_telegram_text(message)
        try:
            self._transport.send_message(text=text)
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
        except Exception as exc:
            return AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=self._clock.now())


def _serialize_webhook_payload(payload: dict) -> bytes:
    """Misma serialización determinista que usa `UrllibWebhookTransport`
    (webhook_transport.py) para su propio chequeo defensivo de tamaño --
    única forma de que ambos midan el mismo payload de la misma manera."""
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return serialized.encode("utf-8")


def _webhook_payload_fits(*, alert_id: str, title: str, severity: Optional[str], body: str) -> bool:
    candidate = {
        "version": "1",
        "event_type": "paper_trading.inspection_alert",
        "alert": {"id": alert_id, "title": title, "body": body, "severity": severity},
    }
    return len(_serialize_webhook_payload(candidate)) <= WEBHOOK_MAX_PAYLOAD_BYTES


def _truncate_webhook_body(*, alert_id: str, title: str, severity: Optional[str], body: str) -> str:
    """Encuentra, por búsqueda binaria sobre la cantidad de caracteres de
    `body`, el prefijo más largo que -- con `_WEBHOOK_BODY_TRUNCATION_MARK`
    agregado -- deja el payload completo dentro de
    `WEBHOOK_MAX_PAYLOAD_BYTES`. Trabaja siempre sobre `str` (nunca
    bytes a medio carácter): cada candidato se vuelve a serializar por
    completo, así que el resultado final siempre es JSON UTF-8 válido.
    Si ni siquiera un cuerpo vacío entra en el límite, devuelve ''
    (el llamador decide si eso sigue sin entrar y falla de forma
    controlada)."""
    low, high = 0, len(body)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = body[:mid]
        if mid < len(body):
            candidate = candidate + _WEBHOOK_BODY_TRUNCATION_MARK
        if _webhook_payload_fits(alert_id=alert_id, title=title, severity=severity, body=candidate):
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _build_webhook_payload(message: NotificationMessage) -> dict:
    """Adapta un NotificationMessage ya renderizado al payload JSON que el
    Webhook transporta (§30). Pura y determinista: nunca muta `message`,
    nunca incluye metadata arbitraria, credenciales, marcas de tiempo
    nuevas ni datos del repositorio -- solo `alert_id`/`title`/`body`/
    `severity` (como texto o `None`), bajo las claves fijas `version`
    (`"1"`) y `event_type` (`"paper_trading.inspection_alert"`).

    Si el payload con el cuerpo completo no entra en
    `WEBHOOK_MAX_PAYLOAD_BYTES`, trunca únicamente `alert.body` (nunca
    título/severidad/id) de forma determinista y seguro para UTF-8 (ver
    `_truncate_webhook_body`), marcando el corte con
    `_WEBHOOK_BODY_TRUNCATION_MARK`. Si incluso con el cuerpo vacío el
    payload seguiría sin entrar, lanza `WebhookTransportError` antes de
    que `UrllibWebhookTransport` intente ninguna conexión real."""
    severity = message.severity.value if message.severity is not None else None
    payload = {
        "version": "1",
        "event_type": "paper_trading.inspection_alert",
        "alert": {"id": message.alert_id, "title": message.title, "body": message.body, "severity": severity},
    }
    if len(_serialize_webhook_payload(payload)) <= WEBHOOK_MAX_PAYLOAD_BYTES:
        return payload

    truncated_body = _truncate_webhook_body(
        alert_id=message.alert_id, title=message.title, severity=severity, body=message.body,
    )
    payload["alert"]["body"] = truncated_body
    if len(_serialize_webhook_payload(payload)) > WEBHOOK_MAX_PAYLOAD_BYTES:
        raise WebhookTransportError("Webhook payload exceeds the maximum allowed size.")
    return payload


class WebhookNotificationChannel:
    """Canal real (Etapa 6.15, §30): entrega vía un webhook HTTP genérico,
    a través de un `WebhookTransport` inyectado y ya configurado
    (webhook_transport.py) -- mismo patrón que
    `TelegramNotificationChannel`/`SlackNotificationChannel`/
    `EmailNotificationChannel` (§27/§28/§29).

    A diferencia de esos tres canales (texto plano), Webhook envía un
    payload JSON estructurado -- ver `_build_webhook_payload()`. Nunca
    conoce `InspectionAlert` (solo `NotificationMessage`), nunca accede
    al repositorio, nunca persiste estado directamente, y nunca decide
    reintentos globales ni por canal -- eso es responsabilidad
    exclusiva de `AlertDeliveryService`/`CompositeNotificationChannel`
    (§25.2). `deliver()` realiza como máximo UNA solicitud HTTP por
    llamada: no reintenta internamente.

    No conoce ni almacena el endpoint ni el secreto de autorización ni
    ningún timeout -- esa configuración queda encapsulada
    exclusivamente en el `transport` ya construido por la Composition
    Root (ver `WebhookEndpointConfig`/`UrllibWebhookTransport`). Los
    únicos atributos propios de este canal son `transport`/`clock`.
    """

    def __init__(
        self,
        *,
        transport: WebhookTransport,
        clock: Clock = SystemClock(),
    ):
        self._transport = transport
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        try:
            payload = _build_webhook_payload(message)
            self._transport.send_payload(payload=payload)
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
        except Exception as exc:
            return AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=self._clock.now())


class CompositeNotificationChannel:
    """Reparte una entrega entre N canales (patrón Strategy + Composite,
    §24.4), con idempotencia persistente por canal (§25.2, Etapa 6.10.1).

    Antes de invocar cada canal, consulta su `InspectionAlertChannelDelivery`
    ya persistido (`alert_id` + nombre de clase del canal):

    - `DELIVERED` -> se omite por completo, nunca se vuelve a invocar
      `channel.deliver()` (ni siquiera si otro canal sigue fallando).
    - `FAILED` (terminal, ese canal ya agotó su propio `max_attempts`) ->
      se omite también, pero su error se sigue reportando como parte
      del fallo agregado.
    - Ausente o `PENDING` -> se invoca `channel.deliver()` (envuelto en
      su propio try/except: un canal que lanza, como los placeholders,
      nunca detiene a los demás) y el resultado -- éxito o fallo, con su
      propio contador de intentos *por canal* -- se persiste de inmediato.

    Todo el estado vive en el repositorio, nunca solo en memoria: una
    reconstrucción de este objeto (o de toda la Composition Root) no
    hace que un canal ya exitoso reciba la alerta de nuevo.

    El resultado agregado es éxito (`success=True`) solo si TODOS los
    canales de la lista terminan `DELIVERED` (en esta pasada o en una
    anterior). `terminal=True` si al menos un canal alcanzó su propio
    `FAILED` -- señal para que `AlertDeliveryService` marque la alerta
    completa como `FAILED` de inmediato, sin esperar a que el contador
    de intentos *de la alerta* también se agote.

    Limitación conocida: la identidad de un canal es `type(channel).__name__`
    (ej. "LoggingNotificationChannel"). Esto asume, igual que
    `_build_notification_channel()` en composition.py (§24.5/§25.3), como
    máximo una instancia por clase de canal dentro de un mismo Composite
    -- exactamente el caso real actual (un flag por tipo de canal en
    `inspection_notifications`). Si en el futuro se necesitaran dos
    instancias del mismo tipo (ej. dos webhooks a URLs distintas),
    haría falta una identidad explícita por instancia, no solo por clase.

    Etapa 6.11 (§26): recibe un `NotificationMessage`, no un
    `InspectionAlert`. El `alert_id` que necesita para su idempotencia
    por canal se recupera de `message.alert_id` (campo explícito desde
    la Etapa 6.11.1, §26.x -- antes vivía en `message.metadata["alert_id"]`,
    sin garantía de tipo ni de validación). `AlertDeliveryService` ya
    valida `message.alert_id == alert.id` antes de invocar `deliver()`,
    así que este Composite puede confiar en que `message.alert_id`
    corresponde exactamente a la alerta que se está entregando.
    """

    def __init__(
        self,
        channels: list,
        repository: PaperTradingRepository,
        max_attempts: int,
        clock: Clock = SystemClock(),
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1.")
        self._channels = list(channels)
        self._repository = repository
        self._max_attempts = max_attempts
        self._clock = clock

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        if not self._channels:
            # Configuración explícita sin canales habilitados (§24.3/§25.3):
            # no-op exitoso, no un error -- no hay nada que pueda fallar.
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())

        alert_id = message.alert_id
        errors: list[str] = []
        all_delivered = True
        any_terminal_failure = False

        for channel in self._channels:
            channel_name = type(channel).__name__
            existing = self._repository.get_alert_channel_delivery(alert_id, channel_name)

            if existing is not None and existing.status == AlertStatus.DELIVERED:
                continue  # ya entregado: nunca se reintenta este canal.

            if existing is not None and existing.status == AlertStatus.FAILED:
                # Terminal: este canal ya agotó su propio max_attempts antes.
                all_delivered = False
                any_terminal_failure = True
                if existing.last_error:
                    errors.append(f"{channel_name}: {existing.last_error}")
                continue

            previous_attempts = existing.delivery_attempts if existing is not None else 0
            now = self._clock.now()
            try:
                result = channel.deliver(message)
            except Exception as exc:
                result = AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=now)

            if result.success:
                self._repository.upsert_alert_channel_delivery(InspectionAlertChannelDelivery(
                    alert_id=alert_id, channel_name=channel_name, status=AlertStatus.DELIVERED,
                    delivery_attempts=previous_attempts + 1, last_error=None,
                    delivered_at=result.delivered_at, updated_at=now,
                ))
                continue

            attempts = previous_attempts + 1
            error_text = result.error_message or "fallo sin mensaje"
            channel_status = AlertStatus.FAILED if attempts >= self._max_attempts else AlertStatus.PENDING
            self._repository.upsert_alert_channel_delivery(InspectionAlertChannelDelivery(
                alert_id=alert_id, channel_name=channel_name, status=channel_status,
                delivery_attempts=attempts, last_error=error_text, delivered_at=None, updated_at=now,
            ))
            all_delivered = False
            errors.append(f"{channel_name}: {error_text}")
            if channel_status == AlertStatus.FAILED:
                any_terminal_failure = True
            logger.warning(
                "Canal de notificación %s falló al entregar la alerta %s (intento %s/%s): %s",
                channel_name, alert_id, attempts, self._max_attempts, error_text,
            )

        return AlertDeliveryResult(
            success=all_delivered,
            error_message="; ".join(errors) if errors else None,
            delivered_at=self._clock.now(),
            terminal=any_terminal_failure,
        )
