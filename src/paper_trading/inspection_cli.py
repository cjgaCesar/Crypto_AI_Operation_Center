"""
CLI administrativa de inspecciones automatizadas de Paper Trading
(Etapa 6.9, endurecida en la Etapa 6.22 con un contrato seguro de
errores).

Mismo patrón que reconciliation_cli.py (Etapa 6.8): construye su propio
PaperTradingContext, con SystemClock/UUIDIdGenerator reales. No conecta
Binance, no importa Streamlit/Dashboard, no inicia ningún scheduler,
**nunca llama repair()**.

Uso:
    python -m src.paper_trading.inspection_cli run
    python -m src.paper_trading.inspection_cli alerts
    python -m src.paper_trading.inspection_cli history --limit 20

Esta etapa no cambia subcomandos, argumentos ni lógica de persistencia/
alertas: solo endurece el manejo de errores (ver `EXIT_*` más abajo).
`run`/`alerts` conservan su contrato de negocio ya aprobado (0 si la
corrida/entrega tuvo éxito total, 1 en caso contrario -- un resultado
de negocio, no un error de la CLI). Ante cualquier excepción no
controlada, nunca se imprime un traceback, una ruta absoluta, SQL, ni
el mensaje interno de la excepción -- solo mensajes fijos y
sanitizados. `KeyboardInterrupt`/`SystemExit` nunca se capturan aquí
(no heredan de `Exception`).
"""

import argparse
import sqlite3
import sys
from decimal import Decimal
from typing import Optional

from src.paper_trading.application import PaperTradingDisabledError
from src.paper_trading.composition import PaperTradingContext, build_paper_trading_context
from src.paper_trading.exceptions import InspectionError
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator
from src.utils.config import load_settings

# --------------------------------------------------------------------------
# Códigos de salida (Etapa 6.22)
# --------------------------------------------------------------------------
EXIT_OK = 0
# 1 se conserva sin cambios para el resultado de negocio ya aprobado desde
# la Etapa 6.9 (corrida/entrega no totalmente exitosa) -- nunca se
# reutiliza como código de error genérico.
EXIT_NOT_FULLY_SUCCESSFUL = 1
EXIT_ARGUMENT_ERROR = 2  # gestionado enteramente por argparse (SystemExit)
EXIT_CONFIG_ERROR = 3
EXIT_DISABLED = 4
EXIT_DATABASE_ERROR = 5
EXIT_BUSINESS_REJECTED = 6  # reservado por consistencia con reconciliation_cli.py; sin uso actual
EXIT_OPERATIONAL_ERROR = 7
EXIT_UNEXPECTED_ERROR = 8

_CONFIG_ERROR_MESSAGE = "Could not load configuration to build the Paper Trading context."
_DISABLED_MESSAGE = "Paper Trading is disabled in configuration."
_DATABASE_ERROR_MESSAGE = "Inspection operation failed due to a database error."
_OPERATIONAL_ERROR_MESSAGE = "Inspection process failed due to a controlled operational error."
_UNEXPECTED_MESSAGE = "Inspection operation failed unexpectedly."


class ConfigurationError(Exception):
    """No se pudo cargar la configuración necesaria (código de salida 3).
    Mismo criterio que `order_cli.ConfigurationError`/
    `backup_cli.ConfigurationError`: nunca incluye rutas completas ni
    credenciales en su mensaje."""


class _UnavailableMarketPriceProvider:
    """La inspección automatizada nunca consulta precios (§23.2)."""

    def get_current_price(self, exchange: str, symbol: str) -> Decimal:
        raise NotImplementedError("La CLI de inspección nunca debería consultar un precio de mercado.")

    def get_current_prices(self, symbols: list[tuple[str, str]]) -> dict[tuple[str, str], Decimal]:
        raise NotImplementedError("La CLI de inspección nunca debería consultar un precio de mercado.")


def _build_context() -> PaperTradingContext:
    try:
        settings = load_settings()
    except Exception:
        raise ConfigurationError(_CONFIG_ERROR_MESSAGE) from None

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
    return EXIT_OK if run.success else EXIT_NOT_FULLY_SUCCESSFUL


def _run_alerts(context: PaperTradingContext) -> int:
    result = context.application.deliver_pending_reconciliation_alerts()
    print(f"Alertas entregadas: {result.delivered_count}")
    print(f"Alertas fallidas: {result.failed_count}")
    return EXIT_OK if result.failed_count == 0 else EXIT_NOT_FULLY_SUCCESSFUL


def _run_history(context: PaperTradingContext, limit: Optional[int]) -> int:
    runs = context.application.fetch_reconciliation_inspection_history(limit=limit)
    if not runs:
        print("Sin corridas registradas todavía.")
        return EXIT_OK
    for run in runs:
        _print_run(run)
        print("-" * 40)
    return EXIT_OK


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

    try:
        context = _build_context()
        if args.command == "run":
            return _run_run(context)
        if args.command == "alerts":
            return _run_alerts(context)
        return _run_history(context, limit=args.limit)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except PaperTradingDisabledError:
        # Defensivo (Etapa 6.5): los casos de uso de inspección
        # deliberadamente no gatean con `_require_enabled()` (§23.13 del
        # diseño), así que esta rama es inalcanzable hoy con el código
        # real; se conserva como defensa en profundidad, igual criterio
        # que `order_cli.py`/`reconciliation_cli.py`.
        print(_DISABLED_MESSAGE, file=sys.stderr)
        return EXIT_DISABLED
    except InspectionError:
        # `InspectionPersistenceError` embebe el texto de la excepción
        # original que causó el fallo de persistencia (potencialmente
        # inseguro) -- nunca se imprime `str(exc)` aquí, solo el
        # mensaje fijo. Cubre también cualquier otra subclase de
        # `InspectionError` no enumerada explícitamente.
        print(_OPERATIONAL_ERROR_MESSAGE, file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    except ValueError as exc:
        # Ej. `--limit 0` en `history` (`_validate_limit()` del
        # repositorio lanza `ValueError`) -- mensaje ya seguro (sin
        # datos internos).
        print(str(exc), file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    except sqlite3.Error:
        print(_DATABASE_ERROR_MESSAGE, file=sys.stderr)
        return EXIT_DATABASE_ERROR
    except Exception:
        print(_UNEXPECTED_MESSAGE, file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR


if __name__ == "__main__":
    sys.exit(main())
