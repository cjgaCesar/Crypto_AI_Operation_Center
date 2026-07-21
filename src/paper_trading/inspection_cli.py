"""
CLI administrativa de inspecciones automatizadas de Paper Trading (Etapa 6.9).

Mismo patrón que reconciliation_cli.py (Etapa 6.8): construye su propio
PaperTradingContext, con SystemClock/UUIDIdGenerator reales. No conecta
Binance, no importa Streamlit/Dashboard, no inicia ningún scheduler,
**nunca llama repair()**.

Uso:
    python -m src.paper_trading.inspection_cli run
    python -m src.paper_trading.inspection_cli alerts
    python -m src.paper_trading.inspection_cli history --limit 20
"""

import argparse
import sys
from decimal import Decimal
from typing import Optional

from src.paper_trading.composition import PaperTradingContext, build_paper_trading_context
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator
from src.utils.config import load_settings


class _UnavailableMarketPriceProvider:
    """La inspección automatizada nunca consulta precios (§23.2)."""

    def get_current_price(self, exchange: str, symbol: str) -> Decimal:
        raise NotImplementedError("La CLI de inspección nunca debería consultar un precio de mercado.")

    def get_current_prices(self, symbols: list[tuple[str, str]]) -> dict[tuple[str, str], Decimal]:
        raise NotImplementedError("La CLI de inspección nunca debería consultar un precio de mercado.")


def _build_context() -> PaperTradingContext:
    settings = load_settings()
    return build_paper_trading_context(
        config=settings.paper_trading,
        clock=SystemClock(),
        id_generator=UUIDIdGenerator(),
        market_price_provider=_UnavailableMarketPriceProvider(),
    )


def _print_run(run: ScheduledInspectionRun) -> None:
    print(f"Corrida: {run.id}")
    print(f"  started_at:  {run.started_at.isoformat()}")
    print(f"  completed_at: {run.completed_at.isoformat()}")
    print(f"  success: {'sí' if run.success else 'no'}")
    if run.report is not None:
        print(
            f"  issues: {run.report.total_issues} (CRITICAL={run.report.critical_count}, "
            f"ERROR={run.report.error_count}, WARNING={run.report.warning_count}, INFO={run.report.info_count})"
        )
    print(
        f"  nuevos={run.new_issue_count} resueltos={run.resolved_issue_count} "
        f"persistentes={run.persistent_issue_count} cambiados={run.changed_issue_count} "
        f"alertas={run.alert_count}"
    )
    if run.error_message:
        print(f"  error: {run.error_message}")


def _run_run(context: PaperTradingContext) -> int:
    run = context.application.run_reconciliation_inspection()
    _print_run(run)
    if context.config.reconciliation_inspection.deliver_alerts:
        result = context.application.deliver_pending_reconciliation_alerts()
        print(f"Alertas entregadas: {result.delivered_count}, fallidas: {result.failed_count}")
    return 0 if run.success else 1


def _run_alerts(context: PaperTradingContext) -> int:
    result = context.application.deliver_pending_reconciliation_alerts()
    print(f"Alertas entregadas: {result.delivered_count}")
    print(f"Alertas fallidas: {result.failed_count}")
    return 0 if result.failed_count == 0 else 1


def _run_history(context: PaperTradingContext, limit: Optional[int]) -> int:
    runs = context.application.fetch_reconciliation_inspection_history(limit=limit)
    if not runs:
        print("Sin corridas registradas todavía.")
        return 0
    for run in runs:
        _print_run(run)
        print("-" * 40)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.paper_trading.inspection_cli",
        description="Inspección automatizada de reconciliación de Paper Trading (Etapa 6.9). Nunca repara.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="Ejecuta una inspección manual y opcionalmente entrega alertas.")
    subparsers.add_parser("alerts", help="Entrega las alertas PENDING ya persistidas.")

    history_parser = subparsers.add_parser("history", help="Lista el historial de corridas (solo lectura).")
    history_parser.add_argument("--limit", type=int, default=None, help="Máximo de corridas a listar.")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    context = _build_context()

    if args.command == "run":
        return _run_run(context)
    if args.command == "alerts":
        return _run_alerts(context)
    return _run_history(context, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
