"""
Pruebas para AlertBuilder (Etapa 6.9): construcción pura de InspectionAlert.
Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.6/§23.7/§23.10.
"""

from datetime import datetime, timezone
from decimal import Decimal

from src.paper_trading.alert_builder import build_alerts, build_inspection_failed_alert, build_system_recovered_alert
from src.paper_trading.alert_models import AlertStatus, AlertType
from src.paper_trading.inspection_comparator import compare_reports
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


def _report(*issues) -> ReconciliationReport:
    return ReconciliationReport(generated_at=_now(), issues=tuple(issues))


class TestNewIssueAlert:
    def test_builds_new_issue_alert(self):
        issue = _issue()
        comparison = compare_reports(None, _report(issue))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.NEW_ISSUE
        assert alerts[0].run_id == "run-1"
        assert alerts[0].id == "a1"
        assert alerts[0].status == AlertStatus.PENDING


class TestResolvedIssueAlert:
    def test_builds_resolved_issue_alert(self):
        issue = _issue()
        comparison = compare_reports(_report(issue), _report())
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.RESOLVED_ISSUE


class TestSeverityChangedAlerts:
    def test_builds_severity_increased_alert(self):
        previous = _issue(severity=IssueSeverity.WARNING)
        current = _issue(severity=IssueSeverity.CRITICAL)
        comparison = compare_reports(_report(previous), _report(current))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert alerts[0].alert_type == AlertType.SEVERITY_INCREASED
        assert alerts[0].severity == IssueSeverity.CRITICAL

    def test_builds_severity_decreased_alert(self):
        previous = _issue(severity=IssueSeverity.CRITICAL)
        current = _issue(severity=IssueSeverity.WARNING)
        comparison = compare_reports(_report(previous), _report(current))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert alerts[0].alert_type == AlertType.SEVERITY_DECREASED


class TestSimultaneousSeverityAndValueChange:
    """Caso 5 (corrección Etapa 6.9, §23.19): cuando severidad Y valor
    cambian a la vez, el comparador produce ambas categorías y el builder
    debe generar dos alertas distintas para el mismo IssueIdentity."""

    def test_builds_two_distinct_alerts_for_same_identity(self):
        previous = _issue(severity=IssueSeverity.WARNING, actual_value=Decimal("100"))
        current = _issue(severity=IssueSeverity.CRITICAL, actual_value=Decimal("200"))
        comparison = compare_reports(_report(previous), _report(current))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1", "a2"])

        assert len(alerts) == 2
        alert_types = {alert.alert_type for alert in alerts}
        assert alert_types == {AlertType.SEVERITY_INCREASED, AlertType.VALUE_CHANGED}

        # Distinta deduplication_key.
        assert alerts[0].deduplication_key != alerts[1].deduplication_key

        # Mismo IssueIdentity para ambas.
        identities = {alert.issue_identity for alert in alerts}
        assert len(identities) == 1


class TestValueChangedAlert:
    def test_builds_value_changed_alert(self):
        previous = _issue(actual_value=Decimal("100"))
        current = _issue(actual_value=Decimal("200"))
        comparison = compare_reports(_report(previous), _report(current))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert alerts[0].alert_type == AlertType.VALUE_CHANGED


class TestInspectionFailedAlert:
    def test_builds_inspection_failed_alert(self):
        alert = build_inspection_failed_alert("run-1", "a1", _now(), "boom")
        assert alert.alert_type == AlertType.INSPECTION_FAILED
        assert alert.issue_identity is None
        assert "boom" in alert.message


class TestSystemRecoveredAlert:
    def test_builds_system_recovered_alert(self):
        alert = build_system_recovered_alert("run-2", "a2", _now(), "boom")
        assert alert.alert_type == AlertType.SYSTEM_RECOVERED
        assert alert.issue_identity is None


class TestDeduplicationKeyStability:
    def test_same_situation_produces_same_key(self):
        issue = _issue()
        comparison = compare_reports(None, _report(issue))
        alerts1 = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        alerts2 = build_alerts(comparison, run_id="run-2", timestamp=_now(), alert_ids=["a2"])
        assert alerts1[0].deduplication_key == alerts2[0].deduplication_key

    def test_key_is_sha256_hex(self):
        issue = _issue()
        comparison = compare_reports(None, _report(issue))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        key = alerts[0].deduplication_key
        assert len(key) == 64
        int(key, 16)  # no lanza si es hexadecimal válido

    def test_different_severity_produces_different_key(self):
        issue_low = _issue(severity=IssueSeverity.WARNING)
        issue_high = _issue(severity=IssueSeverity.CRITICAL)
        comparison_low = compare_reports(None, _report(issue_low))
        comparison_high = compare_reports(None, _report(issue_high))
        alerts_low = build_alerts(comparison_low, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        alerts_high = build_alerts(comparison_high, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert alerts_low[0].deduplication_key != alerts_high[0].deduplication_key


class TestIdsAndTimestampsInjected:
    def test_ids_are_used_in_order(self):
        issue_a = _issue(entity_id="A")
        issue_b = _issue(entity_id="B")
        comparison = compare_reports(None, _report(issue_a, issue_b))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1", "a2"])
        assert {alert.id for alert in alerts} == {"a1", "a2"}

    def test_timestamp_is_used_as_created_at(self):
        issue = _issue()
        comparison = compare_reports(None, _report(issue))
        fixed = datetime(2030, 1, 1, tzinfo=timezone.utc)
        alerts = build_alerts(comparison, run_id="run-1", timestamp=fixed, alert_ids=["a1"])
        assert alerts[0].created_at == fixed


class TestNoAlertOnTextOnlyChanges:
    def test_unchanged_and_persistent_do_not_generate_alerts(self):
        issue = _issue()
        comparison = compare_reports(_report(issue), _report(issue))
        alerts = build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=[])
        assert alerts == ()


class TestNoMutation:
    def test_build_alerts_does_not_mutate_comparison(self):
        issue = _issue()
        comparison = compare_reports(None, _report(issue))
        original_new_issues = comparison.new_issues
        build_alerts(comparison, run_id="run-1", timestamp=_now(), alert_ids=["a1"])
        assert comparison.new_issues == original_new_issues
