"""
Canales de entrega de alertas de inspección -- patrón Strategy (Etapa 6.10).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §24. `InspectionNotificationChannel`
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
6.10: SMTP, Slack API, Telegram API, webhooks HTTP reales, secretos/
tokens/OAuth).
"""

import logging
from typing import Protocol

from src.paper_trading.alert_models import AlertDeliveryResult, InspectionAlert
from src.paper_trading.runtime import Clock, SystemClock

logger = logging.getLogger(__name__)


class InspectionNotificationChannel(Protocol):
    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        """Entrega `alert`. Nunca lanza: captura sus propios errores y los
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

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        try:
            if alert.severity is not None and alert.severity.value in ("CRITICAL", "ERROR"):
                logger.error("[%s] %s -- %s", alert.alert_type.value, alert.title, alert.message)
            elif alert.severity is not None and alert.severity.value == "WARNING":
                logger.warning("[%s] %s -- %s", alert.alert_type.value, alert.title, alert.message)
            else:
                logger.info("[%s] %s -- %s", alert.alert_type.value, alert.title, alert.message)
            return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
        except Exception as exc:
            return AlertDeliveryResult(success=False, error_message=str(exc), delivered_at=self._clock.now())


class NullNotificationChannel:
    """No hace nada: siempre reporta éxito. Solo para pruebas."""

    def __init__(self, clock: Clock = SystemClock()):
        self._clock = clock

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())


class EmailNotificationChannel:
    """Placeholder: SMTP real queda fuera de alcance de la Etapa 6.10.

    No importa `smtplib` ni ninguna librería de correo. `deliver()`
    siempre lanza `NotImplementedError`."""

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        raise NotImplementedError(
            "EmailNotificationChannel todavía no está implementado (SMTP real queda para una etapa posterior)."
        )


class SlackNotificationChannel:
    """Placeholder: la API real de Slack queda fuera de alcance de la Etapa 6.10.

    No importa `slack_sdk` ni realiza ninguna llamada HTTP. `deliver()`
    siempre lanza `NotImplementedError`."""

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        raise NotImplementedError(
            "SlackNotificationChannel todavía no está implementado (la integración con Slack "
            "queda para una etapa posterior)."
        )


class TelegramNotificationChannel:
    """Placeholder: la API real de Telegram queda fuera de alcance de la Etapa 6.10.

    No importa `telegram` ni realiza ninguna llamada HTTP. `deliver()`
    siempre lanza `NotImplementedError`."""

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        raise NotImplementedError(
            "TelegramNotificationChannel todavía no está implementado (la integración con Telegram "
            "queda para una etapa posterior)."
        )


class WebhookNotificationChannel:
    """Placeholder: los webhooks HTTP reales quedan fuera de alcance de la Etapa 6.10.

    No importa `requests`/`aiohttp` ni realiza ninguna conexión de red.
    `deliver()` siempre lanza `NotImplementedError`."""

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        raise NotImplementedError(
            "WebhookNotificationChannel todavía no está implementado (los webhooks HTTP reales "
            "quedan para una etapa posterior)."
        )


class CompositeNotificationChannel:
    """Reparte una entrega entre N canales (patrón Strategy + Composite, §24.4).

    Cada canal se invoca de forma independiente, envuelto en su propio
    try/except: un canal que falla (ya sea devolviendo
    `success=False` o lanzando una excepción, como los placeholders de
    arriba) se registra vía `logging` y no detiene a los demás. El
    resultado agregado es éxito solo si TODOS los canales tuvieron
    éxito -- así una alerta sigue siendo reintentable mientras algún
    canal real siga fallando, aunque el canal de logging (trivial) no
    falle nunca.
    """

    def __init__(self, channels: list, clock: Clock = SystemClock()):
        self._channels = list(channels)
        self._clock = clock

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        errors: list[str] = []
        all_succeeded = True

        for channel in self._channels:
            channel_name = type(channel).__name__
            try:
                result = channel.deliver(alert)
                if not result.success:
                    all_succeeded = False
                    message = result.error_message or "fallo sin mensaje"
                    errors.append(f"{channel_name}: {message}")
                    logger.warning("Canal de notificación %s falló al entregar la alerta %s: %s",
                                    channel_name, alert.id, message)
            except Exception as exc:
                all_succeeded = False
                errors.append(f"{channel_name}: {exc}")
                logger.warning("Canal de notificación %s lanzó una excepción al entregar la alerta %s: %s",
                                channel_name, alert.id, exc)

        return AlertDeliveryResult(
            success=all_succeeded,
            error_message="; ".join(errors) if errors else None,
            delivered_at=self._clock.now(),
        )
