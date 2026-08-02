"""
CLI administrativa de reconciliación de Paper Trading (Etapa 6.8,
endurecida en la Etapa 6.22 con un contrato seguro de errores).

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
defecto -- `--apply` es la única forma de pasar a `dry_run=False`. Esta
etapa no cambia esa semántica, ni renombra subcomandos/argumentos, ni
agrega `--confirm`/`--format`: solo endurece el manejo de errores.

Contrato de resultado de negocio (sin cambios, Etapa 6.8): `inspect`
devuelve 0 si no hay ningún issue CRITICAL/ERROR, 1 si los hay; `repair`
devuelve 0 si la reparación tuvo éxito, 1 si no -- esto NO es un error
de la CLI, es un resultado de negocio legítimo (mismo criterio que
`grep`: "no matches" no es un fallo del programa).

Contrato de errores (Etapa 6.22, nuevo): ver `EXIT_*` más abajo. Ante
cualquier excepción no controlada, nunca se imprime un traceback, una
ruta absoluta, SQL, ni el mensaje interno de la excepción -- solo
mensajes fijos y sanitizados. `KeyboardInterrupt`/`SystemExit` nunca se
capturan aquí (no heredan de `Exception`): `argparse` sigue generando
`SystemExit(2)` para errores de argumentos, y Ctrl+C conserva su
comportamiento normal de intérprete.
"""

import argparse
import sqlite3
import sys
from decimal import Decimal
from typing import Optional

from src.paper_trading.application import PaperTradingDisabledError
from src.paper_trading.composition import PaperTradingContext, build_paper_trading_context
from src.paper_trading.exceptions import ReconciliationConflictError, ReconciliationError, UnsupportedRepairError
from src.paper_trading.reconciliation_models import IssueCode, ReconciliationReport, ReconciliationRepairResult
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator
from src.utils.config import load_settings

# --------------------------------------------------------------------------
# Códigos de salida (Etapa 6.22)
# --------------------------------------------------------------------------
EXIT_OK = 0
# 1 se conserva sin cambios para el resultado de negocio ya aprobado desde
# la Etapa 6.8 (issues encontrados / reparación no exitosa) -- nunca se
# reutiliza como código de error genérico.
EXIT_ISSUES_FOUND = 1
EXIT_ARGUMENT_ERROR = 2  # gestionado enteramente por argparse (SystemExit)
EXIT_CONFIG_ERROR = 3
EXIT_DISABLED = 4
EXIT_DATABASE_ERROR = 5
EXIT_BUSINESS_REJECTED = 6
EXIT_OPERATIONAL_ERROR = 7
EXIT_UNEXPECTED_ERROR = 8

_CONFIG_ERROR_MESSAGE = "Could not load configuration to build the Paper Trading context."
_DISABLED_MESSAGE = "Paper Trading is disabled in configuration."
_DATABASE_ERROR_MESSAGE = "Reconciliation operation failed due to a database error."
_OPERATIONAL_ERROR_MESSAGE = "Reconciliation process failed due to a controlled operational error."
_UNEXPECTED_MESSAGE = "Reconciliation operation failed unexpectedly."


class ConfigurationError(Exception):
    """No se pudo cargar la configuración necesaria (código de salida 3).
    Mismo criterio que `order_cli.ConfigurationError`/
    `backup_cli.ConfigurationError`: nunca incluye rutas completas ni
    credenciales en su mensaje."""


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
    return EXIT_OK if (report.critical_count == 0 and report.error_count == 0) else EXIT_ISSUES_FOUND


def _run_repair(context: PaperTradingContext, apply: bool, issue_codes: Optional[list[str]]) -> int:
    parsed_codes = [IssueCode(code) for code in issue_codes] if issue_codes else None
    result = context.application.repair_reconciliation(issue_codes=parsed_codes, dry_run=not apply)
    _print_repair_result(result)
    return EXIT_OK if result.success else EXIT_ISSUES_FOUND


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

    try:
        context = _build_context()
        if args.command == "inspect":
            return _run_inspect(context)
        return _run_repair(context, apply=args.apply, issue_codes=args.issue_codes)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except PaperTradingDisabledError:
        # Defensivo (Etapa 6.5): `inspect_reconciliation()`/
        # `repair_reconciliation()` deliberadamente no gatean con
        # `_require_enabled()` (§22.11 del diseño -- mantenimiento de
        # datos disponible incluso con paper_trading.enabled=false),
        # así que esta rama es inalcanzable hoy con el código real; se
        # conserva como defensa en profundidad, igual criterio que
        # `order_cli.py`.
        print(_DISABLED_MESSAGE, file=sys.stderr)
        return EXIT_DISABLED
    except (UnsupportedRepairError, ReconciliationConflictError) as exc:
        # Mensajes diseñados para el operador (§8 del ticket): nunca
        # incluyen SQL, rutas absolutas ni datos sensibles -- seguros
        # de imprimir tal cual.
        print(str(exc), file=sys.stderr)
        return EXIT_BUSINESS_REJECTED
    except ReconciliationError:
        # `ReconciliationAuditError` (embebe el texto de la excepción
        # original que causó el fallo de persistencia, potencialmente
        # inseguro) u otra subclase de `ReconciliationError` no
        # enumerada explícitamente arriba -- nunca se imprime
        # `str(exc)` aquí, solo el mensaje fijo.
        print(_OPERATIONAL_ERROR_MESSAGE, file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    except ValueError as exc:
        # Ej. `--issue-code` con un valor que no es un `IssueCode`
        # válido (`IssueCode(code)` lanza `ValueError`) -- mensaje ya
        # seguro (enumera valores válidos, sin datos internos).
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
