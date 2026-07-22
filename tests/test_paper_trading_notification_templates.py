"""
Pruebas para src/paper_trading/notification_templates.py (Etapa 6.11):
NotificationMessage (inmutable, agnóstico a cualquier canal) y
DefaultInspectionNotificationTemplate (renderiza los 7 AlertType
actuales). Ver docs/ARQUITECTURA_PAPER_TRADING.md §26.
"""

import dataclasses
from datetime import datetime, timezone

import pytest

from src.paper_trading.alert_models import AlertType, InspectionAlert
from src.paper_trading.inspection_models import IssueIdentity
from src.paper_trading.notification_templates import DefaultInspectionNotificationTemplate, NotificationMessage
from src.paper_trading.reconciliation_models import IssueSeverity


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)


def _identity(**overrides) -> IssueIdentity:
    defaults = dict(code="CASH_MISMATCH", entity_type="CASH_BALANCE", entity_id="USDT", exchange=None, symbol=None)
    defaults.update(overrides)
    return IssueIdentity(**defaults)


def _alert(**overrides) -> InspectionAlert:
    defaults = dict(
        id="alert-1", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None, issue_code=None,
        severity=None, title="t", message="Balance de efectivo inconsistente.", deduplication_key="k1",
        status=None, delivery_attempts=0, last_error=None, created_at=_now(),
    )
    defaults.update(overrides)
    return InspectionAlert(**defaults)


class TestNotificationMessageImmutability:
    def test_cannot_reassign_a_field(self):
        message = NotificationMessage(title="t", body="b", severity=None, metadata={})
        with pytest.raises(dataclasses.FrozenInstanceError):
            message.title = "other"

    def test_metadata_dict_cannot_be_mutated(self):
        message = NotificationMessage(title="t", body="b", severity=None, metadata={"alert_id": "a1"})
        with pytest.raises(TypeError):
            message.metadata["alert_id"] = "other"

    def test_mutating_the_source_dict_after_construction_does_not_affect_the_message(self):
        source = {"alert_id": "a1"}
        message = NotificationMessage(title="t", body="b", severity=None, metadata=source)
        source["alert_id"] = "mutated"
        assert message.metadata["alert_id"] == "a1"

    def test_metadata_defaults_to_empty(self):
        message = NotificationMessage(title="t", body="b", severity=None)
        assert dict(message.metadata) == {}


class TestNotificationMessageEquality:
    def test_equal_when_all_fields_match(self):
        m1 = NotificationMessage(title="t", body="b", severity=IssueSeverity.WARNING, metadata={"alert_id": "a1"})
        m2 = NotificationMessage(title="t", body="b", severity=IssueSeverity.WARNING, metadata={"alert_id": "a1"})
        assert m1 == m2

    def test_not_equal_when_a_field_differs(self):
        m1 = NotificationMessage(title="t", body="b", severity=None, metadata={})
        m2 = NotificationMessage(title="t", body="different", severity=None, metadata={})
        assert m1 != m2


class TestNotificationMessageRepresentation:
    def test_repr_includes_all_fields(self):
        message = NotificationMessage(title="titulo", body="cuerpo", severity=IssueSeverity.ERROR, metadata={"k": "v"})
        text = repr(message)
        assert "titulo" in text
        assert "cuerpo" in text
        assert "ERROR" in text
        assert "k" in text and "v" in text


class TestDefaultTemplateGeneratesTitlePerAlertType:
    @pytest.mark.parametrize("alert_type,expected_title", [
        (AlertType.NEW_ISSUE, "Nueva incidencia detectada"),
        (AlertType.RESOLVED_ISSUE, "Incidencia resuelta"),
        (AlertType.SEVERITY_INCREASED, "Severidad de incidencia incrementada"),
        (AlertType.SEVERITY_DECREASED, "Severidad de incidencia reducida"),
        (AlertType.VALUE_CHANGED, "Valor de incidencia modificado"),
        (AlertType.INSPECTION_FAILED, "Inspección de reconciliación fallida"),
        (AlertType.SYSTEM_RECOVERED, "Sistema recuperado"),
    ])
    def test_title_matches_alert_type(self, alert_type, expected_title):
        alert = _alert(alert_type=alert_type)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert message.title == expected_title


class TestDefaultTemplateGeneratesBody:
    def test_body_includes_alert_message(self):
        alert = _alert(message="Texto específico de esta alerta.")
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert "Texto específico de esta alerta." in message.body

    def test_body_includes_created_at_as_isoformat(self):
        alert = _alert(created_at=_now())
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert _now().isoformat() in message.body

    def test_body_includes_issue_code_when_present(self):
        alert = _alert(issue_code="CASH_RESERVED_BALANCE_MISMATCH")
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert "CASH_RESERVED_BALANCE_MISMATCH" in message.body

    def test_body_includes_entity_when_issue_identity_present(self):
        alert = _alert(issue_identity=_identity(entity_type="CASH_BALANCE", entity_id="USDT"))
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert "CASH_BALANCE" in message.body
        assert "USDT" in message.body

    def test_body_includes_exchange_and_symbol_when_present(self):
        alert = _alert(issue_identity=_identity(exchange="Binance", symbol="BTCUSDT"))
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert "Binance" in message.body
        assert "BTCUSDT" in message.body

    def test_body_omits_entity_and_code_lines_when_absent(self):
        alert = _alert(alert_type=AlertType.INSPECTION_FAILED, issue_identity=None, issue_code=None)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert "Entidad:" not in message.body
        assert "Código:" not in message.body

    def test_body_never_contains_html_or_markdown_markup(self):
        alert = _alert(issue_identity=_identity())
        message = DefaultInspectionNotificationTemplate().render(alert)
        for forbidden in ("<", ">", "**", "```", "http://", "https://"):
            assert forbidden not in message.title
            assert forbidden not in message.body


class TestDefaultTemplateSeverityAndMetadata:
    def test_severity_is_carried_over_unchanged(self):
        alert = _alert(severity=IssueSeverity.CRITICAL)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert message.severity is IssueSeverity.CRITICAL

    def test_severity_is_none_when_alert_has_no_severity(self):
        alert = _alert(alert_type=AlertType.SYSTEM_RECOVERED, severity=None)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert message.severity is None

    def test_metadata_includes_alert_id_run_id_and_alert_type(self):
        alert = _alert(id="alert-42", run_id="run-7", alert_type=AlertType.VALUE_CHANGED)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert message.metadata["alert_id"] == "alert-42"
        assert message.metadata["run_id"] == "run-7"
        assert message.metadata["alert_type"] == "VALUE_CHANGED"


class TestDefaultTemplateWorksForAllAlertTypes:
    @pytest.mark.parametrize("alert_type", list(AlertType))
    def test_renders_without_error_for_every_alert_type(self, alert_type):
        alert = _alert(alert_type=alert_type, issue_identity=_identity(), issue_code="CODE", severity=IssueSeverity.WARNING)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert message.title
        assert message.body

    @pytest.mark.parametrize("alert_type", [AlertType.INSPECTION_FAILED, AlertType.SYSTEM_RECOVERED])
    def test_renders_without_error_when_issue_fields_are_none(self, alert_type):
        alert = _alert(alert_type=alert_type, issue_identity=None, issue_code=None, severity=None)
        message = DefaultInspectionNotificationTemplate().render(alert)
        assert message.title
        assert message.body
