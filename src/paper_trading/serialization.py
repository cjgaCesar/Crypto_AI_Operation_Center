"""
Helpers de (de)serialización para la persistencia SQLite de Paper Trading (Etapa 6.3,
ampliado en 6.8 para la auditoría de reconciliación).

Se centralizan aquí porque los 7 modelos persistidos comparten el mismo
patrón de conversión para Decimal y datetime, y repetirlo en cada
método de sqlite_repository.py sería puro ruido. Las funciones base son
puras de texto <-> Decimal/datetime, sin depender de sqlite3.

Regla obligatoria (ver docs/ARQUITECTURA_PAPER_TRADING.md, Etapa 6.3):
todo Decimal se guarda como TEXT (`str(value)`) y se reconstruye con
`Decimal(value)` -- nunca REAL, para no perder precisión.

Etapa 6.8 (§22.9): `serialize_reconciliation_report`/
`serialize_repair_operations` sí dependen de tipos concretos
(`ReconciliationReport`/`RepairOperation`) porque `report_json`/
`operations_json` (columnas de `paper_trading_reconciliation_audit`)
deben ser un JSON determinista (`sort_keys=True`) para poder comparar
auditorías como texto -- misma regla Decimal-como-string/datetime-ISO8601/
enum-`.value` que el resto de este módulo.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.alert_models import AlertStatus, AlertType, InspectionAlert
from src.paper_trading.inspection_models import (
    InspectionComparison, IssueIdentity, ScheduledInspectionRun, build_issue_identity,
)
from src.paper_trading.reconciliation_models import (
    IssueCode, IssueSeverity, ReconciliationIssue, ReconciliationReport, RepairOperation,
)


def decimal_to_text(value: Decimal) -> str:
    """str(value) preserva exactamente la representación decimal original."""
    return str(value)


def text_to_decimal(value: str) -> Decimal:
    return Decimal(value)


def optional_decimal_to_text(value: Optional[Decimal]) -> Optional[str]:
    return str(value) if value is not None else None


def optional_text_to_decimal(value: Optional[str]) -> Optional[Decimal]:
    return Decimal(value) if value is not None else None


def datetime_to_text(value: datetime) -> str:
    """.isoformat() preserva la zona horaria (ver Paso 9 de la Etapa 6.3)."""
    return value.isoformat()


def text_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def optional_datetime_to_text(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def optional_text_to_datetime(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value is not None else None


# --- Serialización de reconciliación (Etapa 6.8, ver ARQUITECTURA_PAPER_TRADING.md §22.9) ---
#
# Mismas reglas que arriba (Decimal como string, datetime ISO8601, enum
# .value) más `sort_keys=True` para que el JSON sea determinista byte a
# byte entre dos serializaciones del mismo objeto -- necesario porque
# report_json/operations_json se comparan/auditan como texto.


def _issue_to_dict(issue: ReconciliationIssue) -> dict:
    return {
        "code": issue.code.value,
        "severity": issue.severity.value,
        "entity_type": issue.entity_type,
        "entity_id": issue.entity_id,
        "exchange": issue.exchange,
        "symbol": issue.symbol,
        "description": issue.description,
        "expected_value": optional_decimal_to_text(issue.expected_value),
        "actual_value": optional_decimal_to_text(issue.actual_value),
        "repairable": issue.repairable,
        "suggested_action": issue.suggested_action,
        "detected_at": datetime_to_text(issue.detected_at),
    }


def serialize_reconciliation_report(report: ReconciliationReport) -> str:
    """JSON determinista de un ReconciliationReport completo (Paso 21)."""
    payload = {
        "generated_at": datetime_to_text(report.generated_at),
        "total_issues": report.total_issues,
        "critical_count": report.critical_count,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "info_count": report.info_count,
        "repairable_count": report.repairable_count,
        "is_consistent": report.is_consistent,
        "issues": [_issue_to_dict(issue) for issue in report.issues],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def serialize_repair_operations(operations: tuple[RepairOperation, ...]) -> str:
    """JSON determinista de las operaciones aplicadas/simuladas por un repair() (Paso 21)."""
    payload = [
        {
            "issue_code": operation.issue_code.value,
            "entity_type": operation.entity_type,
            "entity_id": operation.entity_id,
            "field": operation.field,
            "old_value": decimal_to_text(operation.old_value),
            "new_value": decimal_to_text(operation.new_value),
        }
        for operation in operations
    ]
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def deserialize_reconciliation_report(report_json: str) -> ReconciliationReport:
    """Inverso de serialize_reconciliation_report() (Etapa 6.9, §23.10:
    InspectionService necesita reconstruir el reporte anterior para
    compararlo con el actual). Los campos de conteo del payload
    (total_issues/critical_count/...) se ignoran: ReconciliationReport
    los recalcula como @property a partir de `issues`."""
    payload = json.loads(report_json)
    issues = tuple(
        ReconciliationIssue(
            code=IssueCode(item["code"]), severity=IssueSeverity(item["severity"]),
            entity_type=item["entity_type"], entity_id=item["entity_id"],
            exchange=item["exchange"], symbol=item["symbol"], description=item["description"],
            expected_value=optional_text_to_decimal(item["expected_value"]),
            actual_value=optional_text_to_decimal(item["actual_value"]),
            repairable=item["repairable"], suggested_action=item["suggested_action"],
            detected_at=text_to_datetime(item["detected_at"]),
        )
        for item in payload["issues"]
    )
    return ReconciliationReport(generated_at=text_to_datetime(payload["generated_at"]), issues=issues)


# --- Serialización de inspección automatizada (Etapa 6.9, ver ARQUITECTURA_PAPER_TRADING.md §23) ---


def serialize_issue_identity(identity: IssueIdentity) -> dict:
    """Representación JSON-friendly (dict, no string) de un IssueIdentity."""
    return {
        "code": identity.code, "entity_type": identity.entity_type, "entity_id": identity.entity_id,
        "exchange": identity.exchange, "symbol": identity.symbol,
    }


def serialize_inspection_comparison(comparison: InspectionComparison) -> str:
    """JSON determinista de un InspectionComparison completo (Paso 14):
    principalmente para observabilidad (no es una columna directa de
    ninguna tabla, ver §23.8)."""
    def _identities(issues) -> list:
        return sorted(
            (serialize_issue_identity(build_issue_identity(issue)) for issue in issues),
            key=lambda payload: (payload["code"], payload["entity_type"], payload["entity_id"]),
        )

    payload = {
        "new_issue_count": len(comparison.new_issues),
        "resolved_issue_count": len(comparison.resolved_issues),
        "persistent_issue_count": len(comparison.persistent_issues),
        "severity_increased_count": len(comparison.severity_increased),
        "severity_decreased_count": len(comparison.severity_decreased),
        "value_changed_count": len(comparison.value_changed),
        "unchanged_count": len(comparison.unchanged),
        "new_issues": _identities(comparison.new_issues),
        "resolved_issues": _identities(comparison.resolved_issues),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def serialize_inspection_run(run: ScheduledInspectionRun) -> dict:
    """Convierte un ScheduledInspectionRun a un dict de columnas listas
    para persistir en paper_trading_inspection_runs (Paso 12)."""
    report = run.report
    return {
        "id": run.id,
        "started_at": datetime_to_text(run.started_at),
        "completed_at": datetime_to_text(run.completed_at),
        "success": int(run.success),
        "report_json": serialize_reconciliation_report(report) if report is not None else None,
        "issue_count": report.total_issues if report is not None else 0,
        "critical_count": report.critical_count if report is not None else 0,
        "error_count": report.error_count if report is not None else 0,
        "warning_count": report.warning_count if report is not None else 0,
        "info_count": report.info_count if report is not None else 0,
        "previous_run_id": run.previous_run_id,
        "new_issue_count": run.new_issue_count,
        "resolved_issue_count": run.resolved_issue_count,
        "persistent_issue_count": run.persistent_issue_count,
        "changed_issue_count": run.changed_issue_count,
        "alert_count": run.alert_count,
        "error_message": run.error_message,
    }


def deserialize_inspection_run(row: dict) -> ScheduledInspectionRun:
    """Inverso de serialize_inspection_run(): `row` es un dict con las
    mismas claves usadas para persistir (ver sqlite_repository.py)."""
    report_json = row["report_json"]
    return ScheduledInspectionRun(
        id=row["id"], started_at=text_to_datetime(row["started_at"]),
        completed_at=text_to_datetime(row["completed_at"]), success=bool(row["success"]),
        report=deserialize_reconciliation_report(report_json) if report_json is not None else None,
        previous_run_id=row["previous_run_id"], new_issue_count=row["new_issue_count"],
        resolved_issue_count=row["resolved_issue_count"], persistent_issue_count=row["persistent_issue_count"],
        changed_issue_count=row["changed_issue_count"], alert_count=row["alert_count"],
        error_message=row["error_message"],
    )


def serialize_inspection_alert(alert: InspectionAlert) -> dict:
    """Convierte una InspectionAlert a un dict de columnas listas para
    persistir en paper_trading_inspection_alerts (Paso 12)."""
    return {
        "id": alert.id, "run_id": alert.run_id, "alert_type": alert.alert_type.value,
        "issue_key": json.dumps(serialize_issue_identity(alert.issue_identity), sort_keys=True, ensure_ascii=False)
        if alert.issue_identity is not None else None,
        "issue_code": alert.issue_code, "severity": alert.severity.value if alert.severity is not None else None,
        "title": alert.title, "message": alert.message, "deduplication_key": alert.deduplication_key,
        "status": alert.status.value, "delivery_attempts": alert.delivery_attempts, "last_error": alert.last_error,
        "created_at": datetime_to_text(alert.created_at),
        "delivered_at": optional_datetime_to_text(alert.delivered_at),
    }


def deserialize_inspection_alert(row: dict) -> InspectionAlert:
    """Inverso de serialize_inspection_alert(). `issue_identity` se
    reconstruye solo con los datos disponibles en `issue_key` (JSON de
    serialize_issue_identity()); es None si la alerta no corresponde a
    un issue concreto (INSPECTION_FAILED/SYSTEM_RECOVERED)."""
    issue_identity = None
    if row["issue_key"] is not None:
        identity_payload = json.loads(row["issue_key"])
        issue_identity = IssueIdentity(
            code=identity_payload["code"], entity_type=identity_payload["entity_type"],
            entity_id=identity_payload["entity_id"], exchange=identity_payload["exchange"],
            symbol=identity_payload["symbol"],
        )
    return InspectionAlert(
        id=row["id"], run_id=row["run_id"], alert_type=AlertType(row["alert_type"]),
        issue_identity=issue_identity, issue_code=row["issue_code"],
        severity=IssueSeverity(row["severity"]) if row["severity"] is not None else None,
        title=row["title"], message=row["message"], deduplication_key=row["deduplication_key"],
        status=AlertStatus(row["status"]), delivery_attempts=row["delivery_attempts"],
        last_error=row["last_error"], created_at=text_to_datetime(row["created_at"]),
        delivered_at=optional_text_to_datetime(row["delivered_at"]),
    )
