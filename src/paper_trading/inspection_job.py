"""
InspectionJob -- combina timing/IDs/InspectionService/AlertDeliveryService (Etapa 6.9).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.12. No contiene ninguna
regla de comparación ni de reconciliación (eso vive en
InspectionComparator/ReconciliationEngine); solo orquesta el orden de
llamadas y el no-solapamiento.

Lock no reentrante en memoria (`threading.Lock`, `acquire(blocking=False)`):
protege un único proceso, no es un advisory lock de base de datos --
no impide que dos procesos distintos corran run_once() a la vez (ver
§23.12, limitación documentada explícitamente).
"""

import threading
from typing import Optional

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.inspection_models import InspectionJobResult
from src.paper_trading.inspection_service import InspectionService
from src.paper_trading.runtime import Clock, IdGenerator


class InspectionJob:
    """Ejecuta una corrida de inspección (y, opcionalmente, la entrega de
    alertas pendientes), evitando solapamiento dentro del mismo proceso."""

    def __init__(
        self,
        inspection_service: InspectionService,
        alert_delivery_service: AlertDeliveryService,
        clock: Clock,
        id_generator: IdGenerator,
        deliver_alerts: bool = True,
        alert_batch_size: Optional[int] = None,
    ):
        self._inspection_service = inspection_service
        self._alert_delivery_service = alert_delivery_service
        self._clock = clock
        self._id_generator = id_generator
        self._deliver_alerts = deliver_alerts
        self._alert_batch_size = alert_batch_size
        self._lock = threading.Lock()

    def run_once(self) -> InspectionJobResult:
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return InspectionJobResult(
                run_id=None, started_at=None, completed_at=None, success=False, inspection_result=None,
                delivered_count=0, failed_delivery_count=0, skipped=True,
                error_message="Ya hay una inspección en curso en este proceso; se omite este ciclo.",
            )

        try:
            started_at = self._clock.now()
            run_id = self._id_generator.new_inspection_run_id()

            run = self._inspection_service.run_inspection(run_id=run_id, started_at=started_at)
            completed_at = self._clock.now()

            delivered_count = 0
            failed_delivery_count = 0
            delivery_error: Optional[str] = None
            if self._deliver_alerts:
                try:
                    batch_result = self._alert_delivery_service.deliver_pending_alerts(limit=self._alert_batch_size)
                    delivered_count = batch_result.delivered_count
                    failed_delivery_count = batch_result.failed_count
                except Exception as exc:
                    delivery_error = str(exc)

            return InspectionJobResult(
                run_id=run_id, started_at=started_at, completed_at=completed_at, success=run.success,
                inspection_result=run, delivered_count=delivered_count, failed_delivery_count=failed_delivery_count,
                skipped=False, error_message=run.error_message or delivery_error,
            )
        finally:
            self._lock.release()
