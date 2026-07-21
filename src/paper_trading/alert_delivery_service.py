"""
AlertDeliveryService -- entrega de alertas PENDING con reintentos acotados (Etapa 6.9,
ampliado en 6.10 para depender de InspectionNotificationChannel en vez de un sink concreto).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9/§24. No modifica órdenes,
balances ni posiciones; no llama ReconciliationService/repair(); no
ejecuta trading. Un fallo de entrega o de actualización de estado de
una alerta nunca detiene el procesamiento de las demás.

Depende únicamente de `InspectionNotificationChannel` (patrón Strategy,
§24.2): nunca conoce `LoggingInspectionAlertSink`/`CompositeNotificationChannel`/
ningún canal concreto por nombre, y nunca contiene un `if`/`isinstance`
por tipo de canal -- quien decide qué canales existen es la Composition
Root, no este servicio.
"""

from typing import NamedTuple, Optional

from src.paper_trading.alert_models import AlertStatus
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.notification_channels import InspectionNotificationChannel


class AlertDeliveryBatchResult(NamedTuple):
    """Resumen de una corrida de deliver_pending_alerts()."""

    delivered_count: int
    failed_count: int


class AlertDeliveryService:
    """Lee alertas PENDING, las entrega vía un InspectionNotificationChannel
    (típicamente un CompositeNotificationChannel), y actualiza su estado
    (DELIVERED/FAILED, respetando max_attempts)."""

    def __init__(
        self,
        repository: PaperTradingRepository,
        channel: InspectionNotificationChannel,
        max_attempts: int,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1.")
        self._repository = repository
        self._channel = channel
        self._max_attempts = max_attempts

    def deliver_pending_alerts(self, limit: Optional[int] = None) -> AlertDeliveryBatchResult:
        alerts = self._repository.fetch_pending_inspection_alerts(limit=limit)
        delivered_count = 0
        failed_count = 0

        for alert in alerts:
            try:
                result = self._channel.deliver(alert)
                attempts = alert.delivery_attempts + 1
                if result.success:
                    self._repository.update_inspection_alert_delivery(
                        alert_id=alert.id, status=AlertStatus.DELIVERED, delivery_attempts=attempts,
                        last_error=None, delivered_at=result.delivered_at,
                    )
                    delivered_count += 1
                else:
                    new_status = AlertStatus.FAILED if attempts >= self._max_attempts else AlertStatus.PENDING
                    self._repository.update_inspection_alert_delivery(
                        alert_id=alert.id, status=new_status, delivery_attempts=attempts,
                        last_error=result.error_message, delivered_at=None,
                    )
                    failed_count += 1
            except Exception:
                # Un fallo -- del sink o de la propia actualización de estado
                # -- nunca detiene el procesamiento de las demás alertas del lote.
                failed_count += 1
                continue

        return AlertDeliveryBatchResult(delivered_count=delivered_count, failed_count=failed_count)
