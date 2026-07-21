"""
AlertDeliveryService -- entrega de alertas PENDING con reintentos acotados (Etapa 6.9).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9. No modifica órdenes,
balances ni posiciones; no llama ReconciliationService/repair(); no
ejecuta trading. Un fallo de entrega o de actualización de estado de
una alerta nunca detiene el procesamiento de las demás.
"""

from typing import NamedTuple, Optional

from src.paper_trading.alert_models import AlertStatus
from src.paper_trading.alert_sink import InspectionAlertSink
from src.paper_trading.base import PaperTradingRepository


class AlertDeliveryBatchResult(NamedTuple):
    """Resumen de una corrida de deliver_pending_alerts()."""

    delivered_count: int
    failed_count: int


class AlertDeliveryService:
    """Lee alertas PENDING, las entrega vía un InspectionAlertSink, y
    actualiza su estado (DELIVERED/FAILED, respetando max_attempts)."""

    def __init__(
        self,
        repository: PaperTradingRepository,
        sink: InspectionAlertSink,
        max_attempts: int,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1.")
        self._repository = repository
        self._sink = sink
        self._max_attempts = max_attempts

    def deliver_pending_alerts(self, limit: Optional[int] = None) -> AlertDeliveryBatchResult:
        alerts = self._repository.fetch_pending_inspection_alerts(limit=limit)
        delivered_count = 0
        failed_count = 0

        for alert in alerts:
            try:
                result = self._sink.deliver(alert)
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
