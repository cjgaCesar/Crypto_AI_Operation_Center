"""
Modelos de la automatización de inspecciones de reconciliación (Etapa 6.9).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23. Mismo criterio que
reconciliation_models.py: dataclasses frozen, inmutables, que no se
validan como los modelos de dominio -- son la salida de solo lectura de
InspectionService/InspectionComparator/InspectionJob.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.paper_trading.reconciliation_models import ReconciliationIssue, ReconciliationReport


@dataclass(frozen=True, order=True)
class IssueIdentity:
    """Identidad estable de un ReconciliationIssue entre dos inspecciones
    (§23.4): solo QUÉ está mal, nunca CUÁNDO se detectó ni CÓMO se
    describe. `code` es el valor string del IssueCode (no el enum), para
    que esta clase no dependa de la identidad de objeto del enum."""

    code: str
    entity_type: str
    entity_id: str
    exchange: Optional[str]
    symbol: Optional[str]


def build_issue_identity(issue: ReconciliationIssue) -> IssueIdentity:
    """Función pura y determinista (Paso 6): nunca incluye detected_at,
    description, expected_value, actual_value, suggested_action,
    repairable ni severity."""
    return IssueIdentity(
        code=issue.code.value, entity_type=issue.entity_type, entity_id=issue.entity_id,
        exchange=issue.exchange, symbol=issue.symbol,
    )


@dataclass(frozen=True)
class ChangedIssue:
    """Un issue persistente cuya versión anterior y actual difieren en
    algo relevante (severidad, expected_value, actual_value o
    repairable) -- ver §23.5."""

    identity: IssueIdentity
    previous: ReconciliationIssue
    current: ReconciliationIssue


@dataclass(frozen=True)
class InspectionComparison:
    """Resultado de compare_reports() (Paso 7)."""

    new_issues: tuple[ReconciliationIssue, ...]
    resolved_issues: tuple[ReconciliationIssue, ...]
    persistent_issues: tuple[ReconciliationIssue, ...]
    severity_increased: tuple[ChangedIssue, ...]
    severity_decreased: tuple[ChangedIssue, ...]
    value_changed: tuple[ChangedIssue, ...]
    unchanged: tuple[ReconciliationIssue, ...]

    @property
    def changed_issue_count(self) -> int:
        return len(self.severity_increased) + len(self.severity_decreased) + len(self.value_changed)


@dataclass(frozen=True)
class ScheduledInspectionRun:
    """Una corrida persistida de inspección automatizada (Paso 5)."""

    id: str
    started_at: datetime
    completed_at: datetime
    success: bool
    report: Optional[ReconciliationReport]
    previous_run_id: Optional[str]
    new_issue_count: int
    resolved_issue_count: int
    persistent_issue_count: int
    changed_issue_count: int
    alert_count: int
    error_message: Optional[str] = None


@dataclass(frozen=True)
class InspectionJobResult:
    """Resultado de InspectionJob.run_once() (Paso 5)."""

    run_id: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    success: bool
    inspection_result: Optional[ScheduledInspectionRun]
    delivered_count: int
    failed_delivery_count: int
    skipped: bool
    error_message: Optional[str] = None
