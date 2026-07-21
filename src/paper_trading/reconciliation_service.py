"""
ReconciliationService -- orquestación de diagnóstico/reparación (Etapa 6.8).

Coordina ReconciliationEngine (puro) + PaperTradingRepository: lee el
estado completo, invoca el motor, y -- solo si se le pide explícitamente
-- aplica una reparación real de los agregados de reserva
(`CashBalance.reserved_balance`/`Position.reserved_quantity`). Nunca
inventa datos, nunca crea Execution/Trade, nunca cambia un
`Order.status`, nunca corre automáticamente (ni `inspect()` ni
`repair()` se invocan desde `build_paper_trading_context()`, ver §22.11).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §22.6-§22.8 para el diseño
completo de `repair()`: por defecto `dry_run=True` (nunca escribe);
antes de escribir (`dry_run=False`), vuelve a leer `CashBalance`/
`Position` para confirmar que no cambiaron desde el análisis (control
optimista de concurrencia, Paso 28) -- si cambiaron, aborta con
`ReconciliationConflictError` sin escribir nada.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderSide, OrderStatus
from src.paper_trading.exceptions import ReconciliationAuditError, ReconciliationConflictError, UnsupportedRepairError
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.reconciliation_engine import ReconciliationEngine
from src.paper_trading.reconciliation_models import (
    REPAIRABLE_CODES, IssueCode, ReconciliationAuditRecord, ReconciliationReport,
    ReconciliationRepairResult, RepairOperation,
)
from src.paper_trading.serialization import serialize_reconciliation_report, serialize_repair_operations

ZERO = Decimal("0")


def _normalize_zero(value: Decimal) -> Decimal:
    """Decimal("-0") == Decimal("0") numéricamente, pero su representación
    de texto difiere; normaliza siempre al cero positivo exacto (Paso 17,
    punto 5)."""
    return ZERO if value == ZERO else value


class ReconciliationService:
    """Orquesta ReconciliationEngine + PaperTradingRepository. No genera
    IDs ni timestamps: siempre los recibe como argumento (mismo criterio
    que PaperTradingService)."""

    def __init__(self, repository: PaperTradingRepository, engine=ReconciliationEngine):
        self._repository = repository
        self._engine = engine

    def _read_all_state(self):
        orders = self._repository.fetch_orders(limit=None)
        executions = self._repository.fetch_executions(limit=None)
        trades = self._repository.fetch_trades(limit=None)
        positions = self._repository.fetch_positions(include_flat=True)
        cash_balances = self._repository.fetch_cash_balances()
        return orders, executions, trades, positions, cash_balances

    def inspect(self, timestamp: datetime) -> ReconciliationReport:
        """Lee todo el estado persistido y devuelve un ReconciliationReport.
        Nunca escribe nada (Paso 8/Paso 24)."""
        orders, executions, trades, positions, cash_balances = self._read_all_state()
        return self._engine.analyze(orders, executions, trades, positions, cash_balances, timestamp)

    def repair(
        self,
        audit_id: str,
        timestamp: datetime,
        issue_codes: Optional[list[IssueCode]] = None,
        dry_run: bool = True,
    ) -> ReconciliationRepairResult:
        """Repara únicamente los issues reparables (§22.7): recalcula por
        completo `CashBalance.reserved_balance`/`Position.reserved_quantity`
        a partir de las Órdenes PENDING vigentes. `dry_run=True` (por
        defecto) nunca escribe; solo `dry_run=False` persiste, y solo tras
        confirmar que el estado no cambió desde el análisis (Paso 28).
        """
        if issue_codes is not None:
            unsupported = [code for code in issue_codes if code not in REPAIRABLE_CODES]
            if unsupported:
                raise UnsupportedRepairError(
                    "Los siguientes issue_codes no están en la lista de reparaciones automáticas "
                    f"permitidas (§22.7): {[code.value for code in unsupported]}."
                )

        orders, executions, trades, positions, cash_balances = self._read_all_state()
        report = self._engine.analyze(orders, executions, trades, positions, cash_balances, timestamp)

        all_repairable_in_report = {issue.code for issue in report.issues if issue.repairable}
        target_codes = set(issue_codes) if issue_codes is not None else set(REPAIRABLE_CODES)
        codes_to_apply = all_repairable_in_report & target_codes
        skipped_codes = tuple(sorted(all_repairable_in_report - target_codes, key=lambda code: code.value))

        pending_buy_orders = [o for o in orders if o.status == OrderStatus.PENDING and o.side == OrderSide.BUY]
        pending_sell_orders = [o for o in orders if o.status == OrderStatus.PENDING and o.side == OrderSide.SELL]

        operations: list[RepairOperation] = []
        cash_balance_pairs: list[tuple[CashBalance, CashBalance]] = []  # (original, corrected)
        position_pairs: list[tuple[Position, Position]] = []

        if (
            IssueCode.CASH_RESERVED_BALANCE_MISMATCH in codes_to_apply
            or IssueCode.ORPHAN_CASH_RESERVATION in codes_to_apply
        ):
            expected_cash = ZERO
            for order in pending_buy_orders:
                if order.reserved_notional is not None and order.reserved_fee is not None:
                    expected_cash += order.reserved_notional + order.reserved_fee
            expected_cash = _normalize_zero(expected_cash)

            for cash_balance in cash_balances:
                if cash_balance.reserved_balance == expected_cash:
                    continue
                corrected = CashBalance(**{
                    **cash_balance.model_dump(), "reserved_balance": expected_cash, "updated_at": timestamp,
                })
                cash_balance_pairs.append((cash_balance, corrected))
                matched_code = (
                    IssueCode.ORPHAN_CASH_RESERVATION if expected_cash == ZERO
                    else IssueCode.CASH_RESERVED_BALANCE_MISMATCH
                )
                operations.append(RepairOperation(
                    issue_code=matched_code, entity_type="CashBalance", entity_id=cash_balance.currency,
                    field="reserved_balance", old_value=cash_balance.reserved_balance, new_value=expected_cash,
                ))

        if (
            IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH in codes_to_apply
            or IssueCode.ORPHAN_POSITION_RESERVATION in codes_to_apply
        ):
            expected_by_key: dict[tuple[str, str], Decimal] = {}
            for order in pending_sell_orders:
                if order.reserved_quantity is not None:
                    key = (order.exchange, order.symbol)
                    expected_by_key[key] = expected_by_key.get(key, ZERO) + order.reserved_quantity

            all_keys = set(expected_by_key) | {(p.exchange, p.symbol) for p in positions}
            positions_by_key = {(p.exchange, p.symbol): p for p in positions}
            for exchange, symbol in sorted(all_keys):
                position = positions_by_key.get((exchange, symbol))
                if position is None:
                    continue  # nada que corregir sin una Position existente
                expected_quantity = _normalize_zero(expected_by_key.get((exchange, symbol), ZERO))
                if position.reserved_quantity == expected_quantity:
                    continue
                corrected = Position(**{
                    **position.model_dump(), "reserved_quantity": expected_quantity, "updated_at": timestamp,
                })
                position_pairs.append((position, corrected))
                matched_code = (
                    IssueCode.ORPHAN_POSITION_RESERVATION if expected_quantity == ZERO
                    else IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH
                )
                operations.append(RepairOperation(
                    issue_code=matched_code, entity_type="Position", entity_id=f"{exchange}:{symbol}",
                    field="reserved_quantity", old_value=position.reserved_quantity, new_value=expected_quantity,
                ))

        repaired_codes = tuple(sorted({operation.issue_code for operation in operations}, key=lambda code: code.value))

        if not operations:
            audit_record = ReconciliationAuditRecord(
                id=audit_id, started_at=timestamp, completed_at=timestamp, dry_run=dry_run, success=True,
                issue_count=report.total_issues, repaired_count=0,
                report_json=serialize_reconciliation_report(report), operations_json=serialize_repair_operations(()),
            )
            self._repository.save_reconciliation_audit_record(audit_record)
            return ReconciliationRepairResult(
                dry_run=dry_run, success=True, detected_report=report, repaired_issue_codes=(),
                skipped_issue_codes=skipped_codes, cash_balances_changed=(), positions_changed=(),
                operations_applied=(), completed_at=timestamp,
            )

        if dry_run:
            audit_record = ReconciliationAuditRecord(
                id=audit_id, started_at=timestamp, completed_at=timestamp, dry_run=True, success=True,
                issue_count=report.total_issues, repaired_count=len(operations),
                report_json=serialize_reconciliation_report(report),
                operations_json=serialize_repair_operations(tuple(operations)),
            )
            self._repository.save_reconciliation_audit_record(audit_record)
            return ReconciliationRepairResult(
                dry_run=True, success=True, detected_report=report, repaired_issue_codes=repaired_codes,
                skipped_issue_codes=skipped_codes,
                cash_balances_changed=tuple(corrected for _, corrected in cash_balance_pairs),
                positions_changed=tuple(corrected for _, corrected in position_pairs),
                operations_applied=tuple(operations), completed_at=timestamp,
            )

        # dry_run=False: control optimista de concurrencia (Paso 28) antes de escribir nada.
        for original, corrected in cash_balance_pairs:
            current = self._repository.get_cash_balance(corrected.currency)
            if current is None or current.reserved_balance != original.reserved_balance:
                raise ReconciliationConflictError(
                    f"CashBalance({corrected.currency}).reserved_balance cambió entre el análisis y la "
                    "reparación; vuelva a inspeccionar antes de reintentar."
                )
        for original, corrected in position_pairs:
            current = self._repository.get_position(corrected.exchange, corrected.symbol)
            if current is None or current.reserved_quantity != original.reserved_quantity:
                raise ReconciliationConflictError(
                    f"Position({corrected.exchange}:{corrected.symbol}).reserved_quantity cambió entre el "
                    "análisis y la reparación; vuelva a inspeccionar antes de reintentar."
                )

        try:
            audit_record = ReconciliationAuditRecord(
                id=audit_id, started_at=timestamp, completed_at=timestamp, dry_run=False, success=True,
                issue_count=report.total_issues, repaired_count=len(operations),
                report_json=serialize_reconciliation_report(report),
                operations_json=serialize_repair_operations(tuple(operations)),
            )
            self._repository.save_reconciliation_transaction(
                cash_balances=[corrected for _, corrected in cash_balance_pairs],
                positions=[corrected for _, corrected in position_pairs],
                audit_record=audit_record,
            )
        except Exception as exc:
            failure_audit = ReconciliationAuditRecord(
                id=audit_id, started_at=timestamp, completed_at=timestamp, dry_run=False, success=False,
                issue_count=report.total_issues, repaired_count=0,
                report_json=serialize_reconciliation_report(report),
                operations_json=serialize_repair_operations(tuple(operations)), error_message=str(exc),
            )
            try:
                self._repository.save_reconciliation_audit_record(failure_audit)
            except Exception as audit_exc:
                raise ReconciliationAuditError(
                    f"La reparación falló ({exc}) y además no se pudo registrar la auditoría del fallo."
                ) from audit_exc
            raise

        return ReconciliationRepairResult(
            dry_run=False, success=True, detected_report=report, repaired_issue_codes=repaired_codes,
            skipped_issue_codes=skipped_codes,
            cash_balances_changed=tuple(corrected for _, corrected in cash_balance_pairs),
            positions_changed=tuple(corrected for _, corrected in position_pairs),
            operations_applied=tuple(operations), completed_at=timestamp,
        )
