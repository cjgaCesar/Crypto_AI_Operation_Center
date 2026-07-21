"""
CLI administrativa de reconciliación de Paper Trading (Etapa 6.8).

Herramienta manual, separada por completo del Dashboard (que sigue sin
ningún botón administrativo, ver §22.11) y de `src/main.py` (que sigue
sin scheduler ni ejecución automática, sin importar este módulo). No
conecta Binance, no importa Streamlit/Dashboard, no inicia ningún
scheduler, no ejecuta/acepta/llena/cancela ninguna orden -- solo expone
`PaperTradingApplication.inspect_reconciliation()`/`repair_reconciliation()`
(Etapa 6.8) desde la línea de comandos.

Uso:
    python -m src.paper_trading.reconciliation_cli inspect
    python -m src.paper_trading.reconciliation_cli repair --dry-run
    python -m src.paper_trading.reconciliation_cli repair --apply

`repair` sin `--apply` siempre corre en dry-run (nunca escribe), igual
que `PaperTradingApplication.repair_reconciliation(dry_run=True)` por
defecto -- `--apply` es la única forma de pasar a `dry_run=False`.
Código de salida: 0 si no hay ningún issue CRITICAL/ERROR (o si la
reparación tuvo éxito), 1 en caso contrario.
"""

import argparse
import sys
from decimal import Decimal
from typing import Optional

from src.paper_trading.composition import PaperTradingContext, build_paper_trading_context
from src.paper_trading.reconciliation_models import IssueCode, ReconciliationReport, ReconciliationRepairResult
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator
from src.utils.config import load_settings


class _UnavailableMarketPriceProvider:
    """La reconciliación nunca consulta precios (§22.2): un stub que falla
    ruidosamente si alguna vez se le llamara, en vez de conectar Binance
    o cualquier otra fuente de datos real que esta CLI no necesita."""

    def get_current_price(self, exchange: str, symbol: str) -> Decimal:
        raise NotImplementedError(
            "La CLI de reconciliación nunca debería consultar un precio de mercado."
        )

    def get_current_prices(self, symbols: list[tuple[str, str]]) -> dict[tuple[str, str], Decimal]:
        raise NotImplementedError(
            "La CLI de reconciliación nunca debería consultar un precio de mercado."
        )


def _build_context() -> PaperTradingContext:
    settings = load_settings()
    return build_paper_trading_context(
        config=settings.paper_trading,
        clock=SystemClock(),
        id_generator=UUIDIdGenerator(),
        market_price_provider=_UnavailableMarketPriceProvider(),
    )


def _print_report(report: ReconciliationReport) -> None:
    print(f"Reconciliación generada: {report.generated_at.isoformat()}")
    print(
        f"Total de issues: {report.total_issues} "
        f"(CRITICAL={report.critical_count}, ERROR={report.error_count}, "
        f"WARNING={report.warning_count}, INFO={report.info_count})"
    )
    print(f"Reparables automáticamente: {report.repairable_count}")
    print(f"Consistente: {'sí' if report.is_consistent else 'no'}")
    for issue in report.issues:
        print(
            f"  [{issue.severity.value}] {issue.code.value} -- {issue.entity_type} {issue.entity_id}: "
            f"{issue.description}"
        )


def _print_repair_result(result: ReconciliationRepairResult) -> None:
    mode = "DRY-RUN (nada escrito)" if result.dry_run else "APLICADO"
    print(f"Reparación [{mode}] -- éxito: {'sí' if result.success else 'no'}")
    print(f"Issues reparados: {[code.value for code in result.repaired_issue_codes]}")
    print(f"Issues omitidos (no solicitados): {[code.value for code in result.skipped_issue_codes]}")
    for operation in result.operations_applied:
        print(
            f"  {operation.entity_type} {operation.entity_id}.{operation.field}: "
            f"{operation.old_value} -> {operation.new_value} ({operation.issue_code.value})"
        )
    if not result.operations_applied:
        print("  (sin operaciones: nada que reparar)")


def _run_inspect(context: PaperTradingContext) -> int:
    report = context.application.inspect_reconciliation()
    _print_report(report)
    return 0 if (report.critical_count == 0 and report.error_count == 0) else 1


def _run_repair(context: PaperTradingContext, apply: bool, issue_codes: Optional[list[str]]) -> int:
    parsed_codes = [IssueCode(code) for code in issue_codes] if issue_codes else None
    result = context.application.repair_reconciliation(issue_codes=parsed_codes, dry_run=not apply)
    _print_repair_result(result)
    return 0 if result.success else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.paper_trading.reconciliation_cli",
        description="Diagnóstico y reparación explícita de reservas de Paper Trading (Etapa 6.8).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inspect", help="Reporta inconsistencias sin escribir nada.")

    repair_parser = subparsers.add_parser("repair", help="Repara los issues reparables (dry-run por defecto).")
    repair_parser.add_argument(
        "--apply", action="store_true",
        help="Escribe la reparación (por defecto corre en dry-run, sin escribir nada).",
    )
    repair_parser.add_argument(
        "--issue-code", action="append", dest="issue_codes", default=None,
        help="Limita la reparación a este código (puede repetirse). Por defecto, todos los reparables.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    context = _build_context()

    if args.command == "inspect":
        return _run_inspect(context)
    return _run_repair(context, apply=args.apply, issue_codes=args.issue_codes)


if __name__ == "__main__":
    sys.exit(main())
