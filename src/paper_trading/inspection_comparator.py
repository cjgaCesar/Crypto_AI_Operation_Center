"""
InspectionComparator -- comparación pura entre dos ReconciliationReport (Etapa 6.9).

Motor puro, mismo perfil que reconciliation_engine.py: no lee
repositorio, no escribe, no genera IDs ni timestamps, no usa logging,
no importa Service/Application/Dashboard. Ver
docs/ARQUITECTURA_PAPER_TRADING.md §23.5 para el diseño completo.
"""

from typing import Optional

from src.paper_trading.inspection_models import ChangedIssue, InspectionComparison, build_issue_identity
from src.paper_trading.reconciliation_models import IssueSeverity, ReconciliationReport

_SEVERITY_RANK = {
    IssueSeverity.INFO: 0,
    IssueSeverity.WARNING: 1,
    IssueSeverity.ERROR: 2,
    IssueSeverity.CRITICAL: 3,
}


def _severity_rank(severity: IssueSeverity) -> int:
    return _SEVERITY_RANK[severity]


def compare_reports(
    previous_report: Optional[ReconciliationReport],
    current_report: ReconciliationReport,
) -> InspectionComparison:
    """Compara `previous_report` (None si nunca hubo una corrida exitosa
    antes, tratado como un reporte vacío) contra `current_report`,
    clasificando cada ReconciliationIssue por su IssueIdentity (§23.4).
    """
    previous_by_identity = (
        {build_issue_identity(issue): issue for issue in previous_report.issues}
        if previous_report is not None else {}
    )
    current_by_identity = {build_issue_identity(issue): issue for issue in current_report.issues}

    previous_identities = set(previous_by_identity)
    current_identities = set(current_by_identity)

    new_identities = sorted(current_identities - previous_identities)
    resolved_identities = sorted(previous_identities - current_identities)
    persistent_identities = sorted(current_identities & previous_identities)

    new_issues = tuple(current_by_identity[identity] for identity in new_identities)
    resolved_issues = tuple(previous_by_identity[identity] for identity in resolved_identities)
    persistent_issues = tuple(current_by_identity[identity] for identity in persistent_identities)

    severity_increased = []
    severity_decreased = []
    value_changed = []
    unchanged = []

    for identity in persistent_identities:
        previous_issue = previous_by_identity[identity]
        current_issue = current_by_identity[identity]
        previous_rank = _severity_rank(previous_issue.severity)
        current_rank = _severity_rank(current_issue.severity)

        changed = ChangedIssue(identity=identity, previous=previous_issue, current=current_issue)

        if current_rank > previous_rank:
            severity_increased.append(changed)
        elif current_rank < previous_rank:
            severity_decreased.append(changed)
        elif (
            current_issue.expected_value != previous_issue.expected_value
            or current_issue.actual_value != previous_issue.actual_value
            or current_issue.repairable != previous_issue.repairable
        ):
            value_changed.append(changed)
        else:
            unchanged.append(current_issue)

    return InspectionComparison(
        new_issues=new_issues,
        resolved_issues=resolved_issues,
        persistent_issues=persistent_issues,
        severity_increased=tuple(severity_increased),
        severity_decreased=tuple(severity_decreased),
        value_changed=tuple(value_changed),
        unchanged=tuple(unchanged),
    )
