"""
AlertBuilder -- construcción pura de InspectionAlert (Etapa 6.9).

Puro, mismo perfil que reconciliation_engine.py/inspection_comparator.py:
no persiste, no entrega, no genera IDs ni timestamps (los recibe ya
generados), no importa repositorio/Service/Application/Dashboard, no usa
logging. Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.6/§23.10.

`alert_ids` debe traer exactamente tantos elementos como alertas se
vayan a construir (Paso 11): quien llama (InspectionService) ya conoce
ese número de antemano, contando los tamaños de cada bucket de
`InspectionComparison` antes de invocar este módulo.
"""

from datetime import datetime
from typing import Optional

from src.paper_trading.alert_models import AlertStatus, AlertType, InspectionAlert, build_deduplication_key
from src.paper_trading.inspection_models import ChangedIssue, InspectionComparison, build_issue_identity


def _new_issue_alert(issue, run_id: str, alert_id: str, timestamp: datetime, identity) -> InspectionAlert:
    key = build_deduplication_key(AlertType.NEW_ISSUE, issue_identity=identity, severity=issue.severity)
    return InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=AlertType.NEW_ISSUE, issue_identity=identity,
        issue_code=issue.code.value, severity=issue.severity,
        title=f"Nuevo issue: {issue.code.value}",
        message=f"{issue.entity_type} {issue.entity_id}: {issue.description}",
        deduplication_key=key, status=AlertStatus.PENDING, delivery_attempts=0, last_error=None,
        created_at=timestamp,
    )


def _resolved_issue_alert(issue, run_id: str, alert_id: str, timestamp: datetime, identity) -> InspectionAlert:
    key = build_deduplication_key(AlertType.RESOLVED_ISSUE, issue_identity=identity, severity=issue.severity)
    return InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=AlertType.RESOLVED_ISSUE, issue_identity=identity,
        issue_code=issue.code.value, severity=issue.severity,
        title=f"Issue resuelto: {issue.code.value}",
        message=f"{issue.entity_type} {issue.entity_id} ya no presenta este issue.",
        deduplication_key=key, status=AlertStatus.PENDING, delivery_attempts=0, last_error=None,
        created_at=timestamp,
    )


def _severity_changed_alert(
    changed: ChangedIssue, alert_type: AlertType, run_id: str, alert_id: str, timestamp: datetime,
) -> InspectionAlert:
    key = build_deduplication_key(
        alert_type, issue_identity=changed.identity,
        previous_severity=changed.previous.severity, current_severity=changed.current.severity,
    )
    direction = "aumentó" if alert_type == AlertType.SEVERITY_INCREASED else "disminuyó"
    return InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=alert_type, issue_identity=changed.identity,
        issue_code=changed.current.code.value, severity=changed.current.severity,
        title=f"Severidad {direction}: {changed.current.code.value}",
        message=(
            f"{changed.current.entity_type} {changed.current.entity_id}: "
            f"{changed.previous.severity.value} -> {changed.current.severity.value}."
        ),
        deduplication_key=key, status=AlertStatus.PENDING, delivery_attempts=0, last_error=None,
        created_at=timestamp,
    )


def _value_changed_alert(changed: ChangedIssue, run_id: str, alert_id: str, timestamp: datetime) -> InspectionAlert:
    key = build_deduplication_key(
        AlertType.VALUE_CHANGED, issue_identity=changed.identity,
        previous_expected_value=changed.previous.expected_value, previous_actual_value=changed.previous.actual_value,
        current_expected_value=changed.current.expected_value, current_actual_value=changed.current.actual_value,
        previous_repairable=changed.previous.repairable, current_repairable=changed.current.repairable,
    )
    return InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=AlertType.VALUE_CHANGED, issue_identity=changed.identity,
        issue_code=changed.current.code.value, severity=changed.current.severity,
        title=f"Valores cambiaron: {changed.current.code.value}",
        message=(
            f"{changed.current.entity_type} {changed.current.entity_id}: "
            f"expected {changed.previous.expected_value} -> {changed.current.expected_value}, "
            f"actual {changed.previous.actual_value} -> {changed.current.actual_value}."
        ),
        deduplication_key=key, status=AlertStatus.PENDING, delivery_attempts=0, last_error=None,
        created_at=timestamp,
    )


def build_alerts(
    comparison: InspectionComparison,
    run_id: str,
    timestamp: datetime,
    alert_ids: list[str],
) -> tuple[InspectionAlert, ...]:
    """Construye, en orden determinista (new_issues, resolved_issues,
    severity_increased, severity_decreased, value_changed), una alerta
    por cada issue que la aplica (§23.6). `unchanged`/`persistent_issues`
    nunca generan alerta por sí solos."""
    alerts: list[InspectionAlert] = []
    id_iterator = iter(alert_ids)

    for issue in comparison.new_issues:
        alerts.append(_new_issue_alert(issue, run_id, next(id_iterator), timestamp, build_issue_identity(issue)))

    for issue in comparison.resolved_issues:
        alerts.append(_resolved_issue_alert(issue, run_id, next(id_iterator), timestamp, build_issue_identity(issue)))

    for changed in comparison.severity_increased:
        alerts.append(_severity_changed_alert(changed, AlertType.SEVERITY_INCREASED, run_id, next(id_iterator), timestamp))

    for changed in comparison.severity_decreased:
        alerts.append(_severity_changed_alert(changed, AlertType.SEVERITY_DECREASED, run_id, next(id_iterator), timestamp))

    for changed in comparison.value_changed:
        alerts.append(_value_changed_alert(changed, run_id, next(id_iterator), timestamp))

    return tuple(alerts)


def build_inspection_failed_alert(
    run_id: str, alert_id: str, timestamp: datetime, error_message: str,
) -> InspectionAlert:
    key = build_deduplication_key(AlertType.INSPECTION_FAILED, error_message=error_message)
    return InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=AlertType.INSPECTION_FAILED, issue_identity=None,
        issue_code=None, severity=None, title="Inspección de reconciliación falló",
        message=f"ReconciliationService.inspect() lanzó una excepción: {error_message}",
        deduplication_key=key, status=AlertStatus.PENDING, delivery_attempts=0, last_error=None,
        created_at=timestamp,
    )


def build_system_recovered_alert(
    run_id: str, alert_id: str, timestamp: datetime, previous_error_message: Optional[str],
) -> InspectionAlert:
    key = build_deduplication_key(AlertType.SYSTEM_RECOVERED, error_message=previous_error_message)
    return InspectionAlert(
        id=alert_id, run_id=run_id, alert_type=AlertType.SYSTEM_RECOVERED, issue_identity=None,
        issue_code=None, severity=None, title="Inspección de reconciliación se recuperó",
        message=(
            "La inspección anterior había fallado "
            f"({previous_error_message}); esta corrida se completó exitosamente."
        ),
        deduplication_key=key, status=AlertStatus.PENDING, delivery_attempts=0, last_error=None,
        created_at=timestamp,
    )
