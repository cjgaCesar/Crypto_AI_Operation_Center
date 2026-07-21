"""
Modelo de alertas de la automatización de inspecciones (Etapa 6.9).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §23.6-§23.7.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.paper_trading.inspection_models import IssueIdentity
from src.paper_trading.reconciliation_models import IssueSeverity


class AlertType(str, Enum):
    """Tipo de alerta producida por AlertBuilder (§23.6)."""

    NEW_ISSUE = "NEW_ISSUE"
    RESOLVED_ISSUE = "RESOLVED_ISSUE"
    SEVERITY_INCREASED = "SEVERITY_INCREASED"
    SEVERITY_DECREASED = "SEVERITY_DECREASED"
    VALUE_CHANGED = "VALUE_CHANGED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    SYSTEM_RECOVERED = "SYSTEM_RECOVERED"


class AlertStatus(str, Enum):
    """Estado de entrega de una InspectionAlert (§23.9).

    SUPPRESSED queda reservado para una futura función de silenciado
    manual -- ningún camino de código de esta etapa lo produce todavía
    (mismo criterio que OrderType.LIMIT/PositionSide.SHORT en el resto
    del dominio de Paper Trading)."""

    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"


@dataclass(frozen=True)
class InspectionAlert:
    """Una alerta generada por AlertBuilder (Paso 9).

    `issue_identity`/`issue_code`/`severity` son None para
    INSPECTION_FAILED/SYSTEM_RECOVERED (no corresponden a un issue
    concreto, sino al resultado global de la corrida)."""

    id: str
    run_id: str
    alert_type: AlertType
    issue_identity: Optional[IssueIdentity]
    issue_code: Optional[str]
    severity: Optional[IssueSeverity]
    title: str
    message: str
    deduplication_key: str
    status: AlertStatus
    delivery_attempts: int
    last_error: Optional[str]
    created_at: datetime
    delivered_at: Optional[datetime] = None


@dataclass(frozen=True)
class AlertDeliveryResult:
    """Resultado de InspectionAlertSink.deliver() (Paso 9)."""

    success: bool
    error_message: Optional[str]
    delivered_at: datetime


def _decimal_or_none(value: Optional[Decimal]) -> Optional[str]:
    return str(value) if value is not None else None


def _identity_payload(identity: IssueIdentity) -> dict:
    return {
        "code": identity.code, "entity_type": identity.entity_type, "entity_id": identity.entity_id,
        "exchange": identity.exchange, "symbol": identity.symbol,
    }


def build_deduplication_key(
    alert_type: AlertType,
    issue_identity: Optional[IssueIdentity] = None,
    severity: Optional[IssueSeverity] = None,
    previous_severity: Optional[IssueSeverity] = None,
    current_severity: Optional[IssueSeverity] = None,
    previous_expected_value: Optional[Decimal] = None,
    previous_actual_value: Optional[Decimal] = None,
    current_expected_value: Optional[Decimal] = None,
    current_actual_value: Optional[Decimal] = None,
    previous_repairable: Optional[bool] = None,
    current_repairable: Optional[bool] = None,
    error_message: Optional[str] = None,
) -> str:
    """SHA-256 sobre un JSON determinista (§23.7). Nunca usa hash() nativo
    (no es estable entre procesos/ejecuciones). Nunca incluye alert.id,
    run_id, created_at ni detected_at -- ver la tabla de payload por
    AlertType en §23.7."""
    payload: dict = {"alert_type": alert_type.value}

    if alert_type in (AlertType.NEW_ISSUE, AlertType.RESOLVED_ISSUE):
        payload["issue_identity"] = _identity_payload(issue_identity)
        payload["severity"] = severity.value if severity is not None else None
    elif alert_type in (AlertType.SEVERITY_INCREASED, AlertType.SEVERITY_DECREASED):
        payload["issue_identity"] = _identity_payload(issue_identity)
        payload["previous_severity"] = previous_severity.value if previous_severity is not None else None
        payload["current_severity"] = current_severity.value if current_severity is not None else None
    elif alert_type == AlertType.VALUE_CHANGED:
        payload["issue_identity"] = _identity_payload(issue_identity)
        payload["previous_expected_value"] = _decimal_or_none(previous_expected_value)
        payload["previous_actual_value"] = _decimal_or_none(previous_actual_value)
        payload["current_expected_value"] = _decimal_or_none(current_expected_value)
        payload["current_actual_value"] = _decimal_or_none(current_actual_value)
        payload["previous_repairable"] = previous_repairable
        payload["current_repairable"] = current_repairable
    elif alert_type == AlertType.INSPECTION_FAILED:
        payload["error_message"] = error_message
    elif alert_type == AlertType.SYSTEM_RECOVERED:
        payload["previous_error_message"] = error_message

    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
