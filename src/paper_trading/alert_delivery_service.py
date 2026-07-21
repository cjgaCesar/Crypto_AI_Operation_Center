"""
AlertDeliveryService -- entrega de alertas PENDING con reintentos acotados (Etapa 6.9,
ampliado en 6.10 para depender de InspectionNotificationChannel en vez de un sink concreto,
y en 6.10.1 para persistir toda excepción directa del canal -- ver §25.1).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.9/§24/§25. No modifica órdenes,
balances ni posiciones; no llama ReconciliationService/repair(); no
ejecuta trading. Un fallo de entrega o de actualización de estado de
una alerta nunca detiene el procesamiento de las demás.

Depende únicamente de `InspectionNotificationChannel` (patrón Strategy,
§24.2): nunca conoce `LoggingInspectionAlertSink`/`CompositeNotificationChannel`/
ningún canal concreto por nombre, y nunca contiene un `if`/`isinstance`
por tipo de canal -- quien decide qué canales existen es la Composition
Root, no este servicio.

Etapa 6.10.1 (§25.1): ya no depende exclusivamente de que el canal
capture sus propios errores. `deliver_pending_alerts()` envuelve la
llamada a `channel.deliver()` en su propio `try/except`: cualquier
excepción se convierte en un `AlertDeliveryResult(success=False, ...)`
sintético y se procesa exactamente igual que un fallo normal --
`delivery_attempts` se incrementa, `last_error` se guarda, y el estado
pasa a `FAILED` al agotar `max_attempts`. Nunca queda una alerta en
reintento infinito sin rastro.
"""

from typing import NamedTuple, Optional

from src.paper_trading.alert_models import AlertDeliveryResult, AlertStatus
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.notification_channels import InspectionNotificationChannel
from src.paper_trading.runtime import Clock, SystemClock


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
        clock: Clock = SystemClock(),
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1.")
        self._repository = repository
        self._channel = channel
        self._max_attempts = max_attempts
        self._clock = clock

    def deliver_pending_alerts(self, limit: Optional[int] = None) -> AlertDeliveryBatchResult:
        alerts = self._repository.fetch_pending_inspection_alerts(limit=limit)
        delivered_count = 0
        failed_count = 0

        for alert in alerts:
            try:
                result = self._channel.deliver(alert)
            except Exception as exc:
                # Corrección Etapa 6.10.1 (§25.1): una excepción directa del
                # canal (sin pasar por un Composite que la capture) nunca se
                # descarta en silencio -- se trata como cualquier otro fallo
                # de entrega, con su propio registro y conteo de intentos.
                result = AlertDeliveryResult(
                    success=False, error_message=str(exc), delivered_at=self._clock.now(), terminal=False,
                )

            attempts = alert.delivery_attempts + 1
            try:
                if result.success:
                    self._repository.update_inspection_alert_delivery(
                        alert_id=alert.id, status=AlertStatus.DELIVERED, delivery_attempts=attempts,
                        last_error=None, delivered_at=result.delivered_at,
                    )
                    delivered_count += 1
                else:
                    new_status = (
                        AlertStatus.FAILED if (attempts >= self._max_attempts or result.terminal)
                        else AlertStatus.PENDING
                    )
                    self._repository.update_inspection_alert_delivery(
                        alert_id=alert.id, status=new_status, delivery_attempts=attempts,
                        last_error=result.error_message, delivered_at=None,
                    )
                    failed_count += 1
            except Exception:
                # La propia actualización de estado falló (ej. problema de
                # BD) -- nunca detiene el procesamiento de las demás alertas.
                failed_count += 1
                continue

        return AlertDeliveryBatchResult(delivered_count=delivered_count, failed_count=failed_count)
