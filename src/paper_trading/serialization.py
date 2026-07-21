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

from src.paper_trading.reconciliation_models import ReconciliationIssue, ReconciliationReport, RepairOperation


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
