"""
Pruebas para InspectionComparator (Etapa 6.9): comparación pura entre
dos ReconciliationReport. Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.5.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.paper_trading.inspection_comparator import compare_reports
from src.paper_trading.inspection_models import build_issue_identity
from src.paper_trading.reconciliation_models import IssueCode, IssueSeverity, ReconciliationIssue, ReconciliationReport


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _issue(**overrides) -> ReconciliationIssue:
    defaults = dict(
        code=IssueCode.ORPHAN_CASH_RESERVATION, severity=IssueSeverity.ERROR, entity_type="CashBalance",
        entity_id="USDT", exchange=None, symbol=None, description="x", expected_value=Decimal("0"),
        actual_value=Decimal("100"), repairable=True, suggested_action="y", detected_at=_now(),
    )
    defaults.update(overrides)
    return ReconciliationIssue(**defaults)


def _report(*issues, timestamp=None) -> ReconciliationReport:
    return ReconciliationReport(generated_at=timestamp or _now(), issues=tuple(issues))


class TestFirstReport:
    def test_previous_none_all_issues_are_new(self):
        issue = _issue()
        comparison = compare_reports(None, _report(issue))
        assert comparison.new_issues == (issue,)
        assert comparison.resolved_issues == ()
        assert comparison.persistent_issues == ()


class TestIdenticalReports:
    def test_identical_reports_produce_no_changes(self):
        issue = _issue()
        comparison = compare_reports(_report(issue), _report(issue))
        assert comparison.new_issues == ()
        assert comparison.resolved_issues == ()
        assert comparison.persistent_issues == (issue,)
        assert comparison.unchanged == (issue,)
        assert comparison.severity_increased == ()
        assert comparison.severity_decreased == ()
        assert comparison.value_changed == ()


class TestNewResolvedPersistent:
    def test_issue_new(self):
        old = _issue(entity_id="A")
        new = _issue(entity_id="B")
        comparison = compare_reports(_report(old), _report(old, new))
        assert comparison.new_issues == (new,)

    def test_issue_resolved(self):
        old = _issue(entity_id="A")
        comparison = compare_reports(_report(old), _report())
        assert comparison.resolved_issues == (old,)

    def test_issue_persistent(self):
        issue = _issue()
        comparison = compare_reports(_report(issue), _report(issue))
        assert comparison.persistent_issues == (issue,)


class TestSeverityChanges:
    def test_severity_increased(self):
        previous = _issue(severity=IssueSeverity.WARNING)
        current = _issue(severity=IssueSeverity.CRITICAL)
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.severity_increased) == 1
        changed = comparison.severity_increased[0]
        assert changed.previous == previous
        assert changed.current == current

    def test_severity_decreased(self):
        previous = _issue(severity=IssueSeverity.CRITICAL)
        current = _issue(severity=IssueSeverity.WARNING)
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.severity_decreased) == 1
        assert comparison.severity_decreased[0].previous == previous
        assert comparison.severity_decreased[0].current == current

    def test_severity_change_alone_does_not_also_appear_in_value_changed_or_unchanged(self):
        """Cuando SOLO cambia la severidad (expected/actual/repairable
        iguales), el issue no aparece en value_changed ni en unchanged --
        distinto del caso de cambio simultáneo (ver TestSimultaneousChanges)."""
        previous = _issue(severity=IssueSeverity.WARNING)
        current = _issue(severity=IssueSeverity.CRITICAL)
        comparison = compare_reports(_report(previous), _report(current))
        assert comparison.value_changed == ()
        assert comparison.unchanged == ()


class TestValueChanges:
    def test_expected_value_changed(self):
        previous = _issue(expected_value=Decimal("0"))
        current = _issue(expected_value=Decimal("50"))
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.value_changed) == 1
        assert comparison.value_changed[0].previous == previous
        assert comparison.value_changed[0].current == current

    def test_actual_value_changed(self):
        previous = _issue(actual_value=Decimal("100"))
        current = _issue(actual_value=Decimal("200"))
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.value_changed) == 1

    def test_repairable_changed(self):
        previous = _issue(repairable=True)
        current = _issue(repairable=False)
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.value_changed) == 1

    def test_value_change_is_decimal_exact(self):
        previous = _issue(actual_value=Decimal("100.000000001"))
        current = _issue(actual_value=Decimal("100.000000002"))
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.value_changed) == 1


class TestNoAlertOnTextOnlyChanges:
    def test_description_change_does_not_affect_identity(self):
        previous = _issue(description="antiguo")
        current = _issue(description="nuevo")
        comparison = compare_reports(_report(previous), _report(current))
        assert comparison.unchanged == (current,)
        assert comparison.value_changed == ()
        assert comparison.new_issues == ()
        assert comparison.resolved_issues == ()

    def test_detected_at_change_does_not_affect_identity(self):
        now = _now()
        previous = _issue(detected_at=now)
        current = _issue(detected_at=now + timedelta(hours=1))
        comparison = compare_reports(_report(previous), _report(current))
        assert comparison.unchanged == (current,)
        assert comparison.value_changed == ()


class TestSimultaneousChanges:
    """Corrección Etapa 6.9 (auditoría post-aprobación, §23.19): un mismo
    issue puede caer en severity_increased/decreased Y en value_changed a
    la vez -- ya no son mutuamente excluyentes."""

    def test_case_1_severity_increased_and_value_changed_both_fire(self):
        previous = _issue(severity=IssueSeverity.WARNING, actual_value=Decimal("100"))
        current = _issue(severity=IssueSeverity.CRITICAL, actual_value=Decimal("200"))
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.severity_increased) == 1
        assert len(comparison.value_changed) == 1
        assert len(comparison.unchanged) == 0
        assert comparison.severity_increased[0].current == current
        assert comparison.value_changed[0].current == current

    def test_case_2_same_severity_only_value_changed_fires(self):
        previous = _issue(severity=IssueSeverity.ERROR, actual_value=Decimal("100"))
        current = _issue(severity=IssueSeverity.ERROR, actual_value=Decimal("200"))
        comparison = compare_reports(_report(previous), _report(current))
        assert comparison.severity_increased == ()
        assert comparison.severity_decreased == ()
        assert len(comparison.value_changed) == 1
        assert comparison.unchanged == ()

    def test_case_3_severity_increased_without_value_change_only_severity_fires(self):
        previous = _issue(severity=IssueSeverity.ERROR, actual_value=Decimal("100"))
        current = _issue(severity=IssueSeverity.CRITICAL, actual_value=Decimal("100"))
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.severity_increased) == 1
        assert comparison.value_changed == ()
        assert comparison.unchanged == ()

    def test_case_4_no_changes_remains_unchanged(self):
        issue = _issue(severity=IssueSeverity.ERROR, actual_value=Decimal("100"))
        comparison = compare_reports(_report(issue), _report(issue))
        assert comparison.severity_increased == ()
        assert comparison.severity_decreased == ()
        assert comparison.value_changed == ()
        assert comparison.unchanged == (issue,)

    def test_severity_decreased_and_value_changed_both_fire(self):
        previous = _issue(severity=IssueSeverity.CRITICAL, actual_value=Decimal("200"))
        current = _issue(severity=IssueSeverity.WARNING, actual_value=Decimal("100"))
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.severity_decreased) == 1
        assert len(comparison.value_changed) == 1
        assert comparison.unchanged == ()

    def test_repairable_change_combined_with_severity_increase(self):
        previous = _issue(severity=IssueSeverity.WARNING, repairable=True)
        current = _issue(severity=IssueSeverity.CRITICAL, repairable=False)
        comparison = compare_reports(_report(previous), _report(current))
        assert len(comparison.severity_increased) == 1
        assert len(comparison.value_changed) == 1


class TestDeterminismAndPurity:
    def test_order_is_deterministic_regardless_of_input_order(self):
        issue_a = _issue(entity_id="A")
        issue_b = _issue(entity_id="B")
        comparison1 = compare_reports(_report(), _report(issue_a, issue_b))
        comparison2 = compare_reports(_report(), _report(issue_b, issue_a))
        identities1 = [build_issue_identity(issue) for issue in comparison1.new_issues]
        identities2 = [build_issue_identity(issue) for issue in comparison2.new_issues]
        assert identities1 == identities2 == sorted(identities1)

    def test_compare_does_not_mutate_reports(self):
        """ReconciliationReport es un dataclass frozen: la mutación ya es
        estructuralmente imposible, pero confirmamos que el contenido
        sigue siendo exactamente el mismo tras compare_reports()."""
        issue = _issue()
        previous_report = _report(issue)
        current_report = _report(issue)
        compare_reports(previous_report, current_report)
        assert previous_report.issues == (issue,)
        assert current_report.issues == (issue,)
