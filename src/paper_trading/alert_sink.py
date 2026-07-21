"""
InspectionAlertSink -- abstracción de entrega de alertas (Etapa 6.9).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9. Solo dos implementaciones
en esta etapa: `LoggingInspectionAlertSink` (logging real) y
`NullInspectionAlertSink` (para pruebas). Ningún canal externo
(email/Slack/Telegram/webhooks/SMS/push) se implementa todavía.
"""

import logging
from typing import Protocol

from src.paper_trading.alert_models import AlertDeliveryResult, InspectionAlert
from src.paper_trading.runtime import Clock, SystemClock

logger = logging.getLogger(__name__)


class InspectionAlertSink(Protocol):
    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        """Entrega `alert`. Nunca lanza: captura sus propios errores y los
        refleja en el AlertDeliveryResult devuelto."""
        ...


class LoggingInspectionAlertSink:
    """Entrega real: escribe la alerta vía `logging` (nunca `print`).

    El nivel de log depende de la severidad de la alerta (CRITICAL/ERROR
    -> logger.error, WARNING -> logger.warning, resto -> logger.info).
    Captura cualquier excepción del propio logging (ej. un handler mal
    configurado) y la refleja como una entrega fallida, en vez de dejarla
    propagar -- AlertDeliveryService depende de que deliver() nunca lance.

    Recibe un `Clock` inyectado (nunca `datetime.now()` directo, ver
    Paso 4, principio 14): `delivered_at` es responsabilidad del sink,
    ya que forma parte del `AlertDeliveryResult` que este produce.
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


class NullInspectionAlertSink:
    """No hace nada: siempre reporta éxito. Solo para pruebas."""

    def __init__(self, clock: Clock = SystemClock()):
        self._clock = clock

    def deliver(self, alert: InspectionAlert) -> AlertDeliveryResult:
        return AlertDeliveryResult(success=True, error_message=None, delivered_at=self._clock.now())
