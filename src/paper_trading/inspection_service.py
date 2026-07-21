"""
InspectionService -- orquestación de la inspección automatizada (Etapa 6.9).

Ejecuta ReconciliationService.inspect() (Etapa 6.8), compara contra la
última corrida exitosa, construye alertas, las deduplica contra lo ya
persistido, y guarda corrida + alertas en una única transacción atómica.
**Nunca llama repair()** -- ver docs/ARQUITECTURA_PAPER_TRADING.md §23.1/
§23.10/§23.11 para el diseño completo.

No importa Dashboard/Binance/scheduler, no ejecuta SQL directamente
(todo pasa por PaperTradingRepository), no consulta precios, no ejecuta
órdenes, no modifica CashBalance/Position/Order.
"""

from datetime import datetime
from typing import Optional

from src.paper_trading.alert_builder import build_alerts, build_inspection_failed_alert, build_system_recovered_alert
from src.paper_trading.alert_models import InspectionAlert
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.exceptions import InspectionPersistenceError
from src.paper_trading.inspection_comparator import compare_reports
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.runtime import Clock, IdGenerator


class InspectionService:
    """Coordina ReconciliationService + compare_reports() + AlertBuilder +
    PaperTradingRepository. Nunca genera IDs de dominio (Order/Execution/
    Trade) ni llama a ningún método del ciclo de vida de órdenes."""

    def __init__(
        self,
        repository: PaperTradingRepository,
        reconciliation_service: ReconciliationService,
        id_generator: IdGenerator,
        clock: Clock,
    ):
        self._repository = repository
        self._reconciliation_service = reconciliation_service
        self._id_generator = id_generator
        self._clock = clock

    def run_inspection(self, run_id: str, started_at: datetime) -> ScheduledInspectionRun:
        """Ejecuta una inspección completa. Nunca lanza por un problema de
        reconciliación (eso se registra como `success=False`, ver §23.11);
        solo puede lanzar `InspectionPersistenceError` si la persistencia
        misma falla de forma estructural."""
        previous_successful_run = self._repository.get_latest_successful_inspection_run()
        previous_any_run = self._repository.get_latest_inspection_run()
        previous_report = previous_successful_run.report if previous_successful_run is not None else None
        previous_run_id = previous_successful_run.id if previous_successful_run is not None else None

        try:
            current_report = self._reconciliation_service.inspect(started_at)
        except Exception as exc:
            return self._handle_failed_inspection(run_id, started_at, previous_any_run, str(exc))

        comparison = compare_reports(previous_report, current_report)
        alerts_needed = (
            len(comparison.new_issues) + len(comparison.resolved_issues)
            + len(comparison.severity_increased) + len(comparison.severity_decreased)
            + len(comparison.value_changed)
        )
        recovered = previous_any_run is not None and not previous_any_run.success

        total_ids_needed = alerts_needed + (1 if recovered else 0)
        alert_ids = [self._id_generator.new_inspection_alert_id() for _ in range(total_ids_needed)]

        completed_at = self._clock.now()

        alerts: list[InspectionAlert] = list(
            build_alerts(comparison, run_id=run_id, timestamp=completed_at, alert_ids=alert_ids[:alerts_needed])
        )
        if recovered:
            alerts.append(build_system_recovered_alert(
                run_id, alert_ids[alerts_needed], completed_at, previous_any_run.error_message,
            ))

        deduped_alerts = self._drop_duplicates(alerts)

        run = ScheduledInspectionRun(
            id=run_id, started_at=started_at, completed_at=completed_at, success=True, report=current_report,
            previous_run_id=previous_run_id, new_issue_count=len(comparison.new_issues),
            resolved_issue_count=len(comparison.resolved_issues),
            persistent_issue_count=len(comparison.persistent_issues),
            changed_issue_count=comparison.changed_issue_count, alert_count=len(deduped_alerts),
        )
        self._persist_with_fallback(run, deduped_alerts)
        return run

    def _handle_failed_inspection(
        self, run_id: str, started_at: datetime, previous_any_run: Optional[ScheduledInspectionRun],
        error_message: str,
    ) -> ScheduledInspectionRun:
        completed_at = self._clock.now()
        alert_id = self._id_generator.new_inspection_alert_id()
        failure_alert = build_inspection_failed_alert(run_id, alert_id, completed_at, error_message)
        deduped_alerts = self._drop_duplicates([failure_alert])

        run = ScheduledInspectionRun(
            id=run_id, started_at=started_at, completed_at=completed_at, success=False, report=None,
            previous_run_id=previous_any_run.id if previous_any_run is not None else None,
            new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0, changed_issue_count=0,
            alert_count=len(deduped_alerts), error_message=error_message,
        )
        self._persist_with_fallback(run, deduped_alerts)
        return run

    def _drop_duplicates(self, alerts: list[InspectionAlert]) -> list[InspectionAlert]:
        """Filtra cualquier alerta cuya deduplication_key ya exista
        persistida (§23.7) -- nunca se intenta un INSERT que violaría la
        restricción UNIQUE."""
        return [
            alert for alert in alerts
            if self._repository.get_inspection_alert_by_deduplication_key(alert.deduplication_key) is None
        ]

    def _persist_with_fallback(self, run: ScheduledInspectionRun, alerts: list[InspectionAlert]) -> None:
        try:
            self._repository.save_inspection_run_transaction(run, alerts)
        except Exception as exc:
            failure_run = ScheduledInspectionRun(
                id=run.id, started_at=run.started_at, completed_at=run.completed_at, success=False, report=None,
                previous_run_id=run.previous_run_id, new_issue_count=0, resolved_issue_count=0,
                persistent_issue_count=0, changed_issue_count=0, alert_count=0,
                error_message=f"Fallo al persistir la corrida: {exc}",
            )
            try:
                self._repository.save_inspection_run_transaction(failure_run, [])
            except Exception as inner_exc:
                raise InspectionPersistenceError(
                    f"No se pudo persistir la corrida {run.id} ni registrar su fallo: {inner_exc}"
                ) from inner_exc
            raise InspectionPersistenceError(f"No se pudo persistir la corrida {run.id}: {exc}") from exc
