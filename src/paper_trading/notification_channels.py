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

Los 4 canales placeholder (`EmailNotificationChannel`,
`SlackNotificationChannel`, `TelegramNotificationChannel`,
`WebhookNotificationChannel`) NO realizan ninguna conexión real: no
importan `smtplib`, `requests`, `slack_sdk`, `telegram` ni `aiohttp`.
Simplemente lanzan `NotImplementedError` con un mensaje explícito --
quedan preparados para una etapa posterior (fuera de alcance de la
6.10/6.10.1/6.11: SMTP, Slack API, Telegram API, webhooks HTTP reales,
secretos/tokens/OAuth).

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
"""

import logging
from typing import Protocol

from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus, InspectionAlertChannelDelivery
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.notification_templates import NotificationMessage
from src.paper_trading.runtime import Clock, SystemClock

logger = logging.getLogger(__name__)


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


class EmailNotificationChannel:
    """Placeholder: SMTP real queda fuera de alcance de la Etapa 6.10.

    No importa `smtplib` ni ninguna librería de correo. `deliver()`
    siempre lanza `NotImplementedError`."""

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        raise NotImplementedError(
            "EmailNotificationChannel todavía no está implementado (SMTP real queda para una etapa posterior)."
        )


class SlackNotificationChannel:
    """Placeholder: la API real de Slack queda fuera de alcance de la Etapa 6.10.

    No importa `slack_sdk` ni realiza ninguna llamada HTTP. `deliver()`
    siempre lanza `NotImplementedError`."""

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        raise NotImplementedError(
            "SlackNotificationChannel todavía no está implementado (la integración con Slack "
            "queda para una etapa posterior)."
        )


class TelegramNotificationChannel:
    """Placeholder: la API real de Telegram queda fuera de alcance de la Etapa 6.10.

    No importa `telegram` ni realiza ninguna llamada HTTP. `deliver()`
    siempre lanza `NotImplementedError`."""

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        raise NotImplementedError(
            "TelegramNotificationChannel todavía no está implementado (la integración con Telegram "
            "queda para una etapa posterior)."
        )


class WebhookNotificationChannel:
    """Placeholder: los webhooks HTTP reales quedan fuera de alcance de la Etapa 6.10.

    No importa `requests`/`aiohttp` ni realiza ninguna conexión de red.
    `deliver()` siempre lanza `NotImplementedError`."""

    def deliver(self, message: NotificationMessage) -> AlertDeliveryResult:
        raise NotImplementedError(
            "WebhookNotificationChannel todavía no está implementado (los webhooks HTTP reales "
            "quedan para una etapa posterior)."
        )


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
