"""
Modelo de hallazgos del subsistema de reconciliación (Etapa 6.8).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §22 para el diseño completo.
Estos tipos son deliberadamente inmutables (`dataclass(frozen=True)`,
mismo criterio que `PaperTradingContext` en composition.py) y no se
validan como los modelos de dominio (Order/Position/...): no son
entidades que se persistan directamente, son la salida, de solo
lectura, de `ReconciliationEngine.analyze()`.

`IssueSeverity`/`IssueCode` viven aquí -- no en enums.py -- porque
pertenecen al subsistema de reconciliación, no al dominio de trading
(Order/Position/Trade/CashBalance) que enums.py describe.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.paper_trading.models import CashBalance, Position


class IssueSeverity(str, Enum):
    """Severidad de un ReconciliationIssue (ver §22.3)."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IssueCode(str, Enum):
    """Código estable de un ReconciliationIssue -- nunca se usa un mensaje
    libre como identificador principal (ver Paso 6). 20 códigos: los 17
    sugeridos por el enunciado más 3 adiciones justificadas
    (`ORPHAN_EXECUTION`, `FILLED_ORDER_EXECUTION_MISMATCH`, `NO_ACTIVITY`
    -- ver §22.3 para la justificación de cada una)."""

    PENDING_BUY_MISSING_RESERVATION = "PENDING_BUY_MISSING_RESERVATION"
    PENDING_SELL_MISSING_RESERVATION = "PENDING_SELL_MISSING_RESERVATION"
    PENDING_BUY_RESERVED_CASH_MISMATCH = "PENDING_BUY_RESERVED_CASH_MISMATCH"
    PENDING_SELL_RESERVED_QUANTITY_MISMATCH = "PENDING_SELL_RESERVED_QUANTITY_MISMATCH"
    PENDING_ORDER_INVALID_RESERVED_PRICE = "PENDING_ORDER_INVALID_RESERVED_PRICE"
    ORDER_RESERVATION_SIDE_MISMATCH = "ORDER_RESERVATION_SIDE_MISMATCH"
    TERMINAL_ORDER_HAS_RESERVATION = "TERMINAL_ORDER_HAS_RESERVATION"
    CASH_RESERVED_BALANCE_MISMATCH = "CASH_RESERVED_BALANCE_MISMATCH"
    POSITION_RESERVED_QUANTITY_MISMATCH = "POSITION_RESERVED_QUANTITY_MISMATCH"
    ORPHAN_CASH_RESERVATION = "ORPHAN_CASH_RESERVATION"
    ORPHAN_POSITION_RESERVATION = "ORPHAN_POSITION_RESERVATION"
    NEGATIVE_AVAILABLE_CASH = "NEGATIVE_AVAILABLE_CASH"
    NEGATIVE_AVAILABLE_QUANTITY = "NEGATIVE_AVAILABLE_QUANTITY"
    FILLED_ORDER_WITHOUT_EXECUTION = "FILLED_ORDER_WITHOUT_EXECUTION"
    FILLED_ORDER_EXECUTION_MISMATCH = "FILLED_ORDER_EXECUTION_MISMATCH"
    MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER = "MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER"
    EXECUTION_FOR_NON_FILLED_ORDER = "EXECUTION_FOR_NON_FILLED_ORDER"
    ORPHAN_EXECUTION = "ORPHAN_EXECUTION"
    SELL_FILLED_WITHOUT_TRADE = "SELL_FILLED_WITHOUT_TRADE"
    TRADE_WITHOUT_EXIT_EXECUTION = "TRADE_WITHOUT_EXIT_EXECUTION"
    POSITION_PNL_INCONSISTENT = "POSITION_PNL_INCONSISTENT"
    NO_ACTIVITY = "NO_ACTIVITY"


# Severidad fija por código (§22.3) -- una tabla, no un `if/elif` disperso,
# para que agregar un código nuevo no pueda olvidar declarar su severidad.
_SEVERITY_BY_CODE: dict[IssueCode, IssueSeverity] = {
    IssueCode.NEGATIVE_AVAILABLE_CASH: IssueSeverity.CRITICAL,
    IssueCode.NEGATIVE_AVAILABLE_QUANTITY: IssueSeverity.CRITICAL,
    IssueCode.PENDING_BUY_RESERVED_CASH_MISMATCH: IssueSeverity.CRITICAL,
    IssueCode.PENDING_SELL_RESERVED_QUANTITY_MISMATCH: IssueSeverity.CRITICAL,
    IssueCode.PENDING_ORDER_INVALID_RESERVED_PRICE: IssueSeverity.CRITICAL,
    IssueCode.ORDER_RESERVATION_SIDE_MISMATCH: IssueSeverity.CRITICAL,
    IssueCode.FILLED_ORDER_WITHOUT_EXECUTION: IssueSeverity.CRITICAL,
    IssueCode.FILLED_ORDER_EXECUTION_MISMATCH: IssueSeverity.CRITICAL,
    IssueCode.EXECUTION_FOR_NON_FILLED_ORDER: IssueSeverity.CRITICAL,
    IssueCode.ORPHAN_EXECUTION: IssueSeverity.CRITICAL,
    IssueCode.TRADE_WITHOUT_EXIT_EXECUTION: IssueSeverity.CRITICAL,
    IssueCode.SELL_FILLED_WITHOUT_TRADE: IssueSeverity.CRITICAL,
    IssueCode.PENDING_BUY_MISSING_RESERVATION: IssueSeverity.ERROR,
    IssueCode.PENDING_SELL_MISSING_RESERVATION: IssueSeverity.ERROR,
    IssueCode.ORPHAN_CASH_RESERVATION: IssueSeverity.ERROR,
    IssueCode.ORPHAN_POSITION_RESERVATION: IssueSeverity.ERROR,
    IssueCode.CASH_RESERVED_BALANCE_MISMATCH: IssueSeverity.ERROR,
    IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH: IssueSeverity.ERROR,
    IssueCode.TERMINAL_ORDER_HAS_RESERVATION: IssueSeverity.ERROR,
    IssueCode.POSITION_PNL_INCONSISTENT: IssueSeverity.WARNING,
    IssueCode.MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER: IssueSeverity.WARNING,
    IssueCode.NO_ACTIVITY: IssueSeverity.INFO,
}

# Códigos con una reparación automática determinista permitida (§22.7).
# Todo lo que no está aquí es repairable=False: exigiría crear una
# Execution/Trade, cambiar un OrderStatus, o inventar un precio/fee.
REPAIRABLE_CODES: frozenset[IssueCode] = frozenset({
    IssueCode.CASH_RESERVED_BALANCE_MISMATCH,
    IssueCode.ORPHAN_CASH_RESERVATION,
    IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH,
    IssueCode.ORPHAN_POSITION_RESERVATION,
})


def severity_for(code: IssueCode) -> IssueSeverity:
    """Severidad fija de `code` (§22.3). No es configurable por quien llama."""
    return _SEVERITY_BY_CODE[code]


@dataclass(frozen=True)
class ReconciliationIssue:
    """Un hallazgo individual de ReconciliationEngine.analyze() (Paso 5)."""

    code: IssueCode
    severity: IssueSeverity
    entity_type: str
    entity_id: str
    exchange: Optional[str]
    symbol: Optional[str]
    description: str
    expected_value: Optional[Decimal]
    actual_value: Optional[Decimal]
    repairable: bool
    suggested_action: str
    detected_at: datetime


@dataclass(frozen=True)
class ReconciliationReport:
    """Resultado completo de ReconciliationEngine.analyze() (Paso 5)."""

    generated_at: datetime
    issues: tuple[ReconciliationIssue, ...] = field(default_factory=tuple)

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == IssueSeverity.CRITICAL)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == IssueSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == IssueSeverity.INFO)

    @property
    def repairable_count(self) -> int:
        return sum(1 for issue in self.issues if issue.repairable)

    @property
    def is_consistent(self) -> bool:
        """True si no hay ningún issue CRITICAL/ERROR/WARNING (INFO no cuenta, ver §22.3)."""
        return self.critical_count == 0 and self.error_count == 0 and self.warning_count == 0


@dataclass(frozen=True)
class RepairOperation:
    """Una corrección individual, aplicada o simulada, dentro de un
    ReconciliationRepairResult (Paso 18). Siempre corresponde a
    recalcular por completo un campo agregado (nunca un incremento/
    decremento aproximado, ver §22.6 Paso 17)."""

    issue_code: IssueCode
    entity_type: str
    entity_id: str
    field: str
    old_value: Decimal
    new_value: Decimal


@dataclass(frozen=True)
class ReconciliationAuditRecord:
    """Una fila inmutable de paper_trading_reconciliation_audit (Paso 20).

    `id`/`started_at`/`completed_at` siempre inyectados por quien llama
    (IdGenerator/Clock) -- nunca generados dentro del repositorio."""

    id: str
    started_at: datetime
    completed_at: datetime
    dry_run: bool
    success: bool
    issue_count: int
    repaired_count: int
    report_json: str
    operations_json: str
    error_message: Optional[str] = None


@dataclass(frozen=True)
class ReconciliationRepairResult:
    """Resultado de ReconciliationService.repair() (Paso 18)."""

    dry_run: bool
    success: bool
    detected_report: ReconciliationReport
    repaired_issue_codes: tuple[IssueCode, ...]
    skipped_issue_codes: tuple[IssueCode, ...]
    cash_balances_changed: tuple[CashBalance, ...]
    positions_changed: tuple[Position, ...]
    operations_applied: tuple[RepairOperation, ...]
    completed_at: datetime
