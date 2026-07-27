"""
CLI administrativa de backup, verificación y restauración de la base
SQLite de Paper Trading (Etapa 6.20).

Uso:
    python -m src.paper_trading.backup_cli backup \\
        --output backups/paper_trading_2026-07-27.sqlite
    python -m src.paper_trading.backup_cli verify \\
        --backup-path backups/paper_trading_2026-07-27.sqlite
    python -m src.paper_trading.backup_cli verify --configured-database --full
    python -m src.paper_trading.backup_cli restore \\
        --backup-path backups/paper_trading_2026-07-27.sqlite --confirm

Decisión arquitectónica: esta CLI solo traduce línea de comandos <->
`SQLitePaperTradingBackupService` (`sqlite_backup.py`, que contiene toda
la lógica SQLite reutilizable: `sqlite3.Connection.backup()`,
publicación atómica vía `os.replace()`, verificación de integridad y
schema, detección de escritor activo). No duplica ninguna operación
SQLite compleja aquí -- ver `sqlite_backup.py` para el diseño completo.

No importa `PaperTradingApplication`/`PaperTradingService`/ningún motor
ni transporte de notificaciones: el subsistema de backup es
completamente independiente del dominio de trading (nunca construye un
`PaperTradingContext`).

Configuración: la base ORIGEN de Paper Trading se resuelve
exclusivamente desde `settings.paper_trading.database_path` (vía
`load_settings()`) -- nunca `--database-path`/`--source-database`/
`--connection-url`. Sí se permite `--output`/`--backup-path` para
elegir dónde vive el archivo de backup/restauración, que es un
concepto distinto de "la base productiva configurada".

`backup`/`verify` pueden ejecutarse aunque `paper_trading.enabled` sea
`false` (son operaciones administrativas de protección/lectura, no de
trading) -- nunca comprueban ese flag, nunca usan el gate de
`order_cli.py`. La seguridad de `restore` se basa en `--confirm`,
validación previa del backup, backup previo automático y reemplazo
atómico, no en `paper_trading.enabled`.
"""

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from src.paper_trading.sqlite_backup import (
    BackupDestinationExistsError,
    BackupIntegrityError,
    BackupPathConflictError,
    BackupSchemaError,
    BackupSourceNotFoundError,
    DatabaseBusyError,
    PaperTradingBackupError,
    RestoreError,
    SQLitePaperTradingBackupService,
)
from src.utils.config import Settings, load_settings

EXIT_OK = 0
EXIT_ARGUMENT_ERROR = 2
EXIT_CONFIG_ERROR = 3
EXIT_NOT_FOUND = 4
EXIT_CONFIRMATION_REQUIRED = 5
EXIT_PATH_CONFLICT = 6
EXIT_INTEGRITY_FAILED = 7
EXIT_SCHEMA_INVALID = 8
EXIT_DATABASE_BUSY = 9
EXIT_OPERATIONAL_ERROR = 10
EXIT_UNEXPECTED_ERROR = 11

_CONFIRMATION_MESSAGE = "Confirmation required: pass --confirm to authorize this write."
_UNEXPECTED_MESSAGE = "Backup operation failed unexpectedly."


class ConfigurationError(Exception):
    """No se pudo cargar la configuración necesaria (código de salida 3).
    Mismo criterio que `order_cli.ConfigurationError`/
    `portfolio_cli.ConfigurationError`: nunca incluye rutas completas ni
    credenciales en su mensaje."""


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

def _load_settings() -> Settings:
    try:
        return load_settings()
    except Exception:
        raise ConfigurationError("Could not load configuration to resolve the Paper Trading database path.") from None


# --------------------------------------------------------------------------
# Formato de salida (solo biblioteca estándar: sin tabulate/rich/pandas)
# --------------------------------------------------------------------------

def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def _result_to_dict(result: Any) -> dict:
    return {field.name: _serialize(getattr(result, field.name)) for field in dataclasses.fields(result)}


def _format_value_for_table(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(value) if value else "-"
    return str(value)


def render_key_value(payload: dict) -> str:
    return "\n".join(f"{key}: {_format_value_for_table(value)}" for key, value in payload.items())


def render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def _print_result(result: Any, output_format: str) -> None:
    payload = _result_to_dict(result)
    if output_format == "json":
        print(render_json(payload))
    else:
        print(render_key_value(payload))


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def _build_common_parser() -> argparse.ArgumentParser:
    """`--format`, compartido entre el parser raíz y los tres
    subparsers -- mismo patrón de parser padre +
    `argument_default=argparse.SUPPRESS` aprobado en la Etapa 6.18.1:
    se acepta tanto antes como después del subcomando."""
    parser = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    parser.add_argument("--format", dest="format", choices=["table", "json"], help="Formato de salida (default: table).")
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _build_common_parser()

    parser = argparse.ArgumentParser(
        prog="python -m src.paper_trading.backup_cli",
        description="CLI administrativa de backup/verify/restore de la base SQLite de Paper Trading (Etapa 6.20).",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser(
        "backup", parents=[common], help="Crea una copia consistente de la base de Paper Trading configurada.",
    )
    backup_parser.add_argument("--output", required=True, help="Ruta del archivo de backup a crear.")
    backup_parser.add_argument(
        "--overwrite", action="store_true",
        help="Permite sobrescribir un backup ya existente en --output (requiere --confirm).",
    )
    backup_parser.add_argument(
        "--confirm", action="store_true",
        help="Obligatorio únicamente cuando --overwrite se usa sobre un destino que ya existe.",
    )

    verify_parser = subparsers.add_parser(
        "verify", parents=[common], help="Verifica integridad física y schema mínimo de Paper Trading.",
    )
    verify_target = verify_parser.add_mutually_exclusive_group(required=True)
    verify_target.add_argument("--backup-path", dest="backup_path", default=None, help="Ruta de un backup a verificar.")
    verify_target.add_argument(
        "--configured-database", dest="configured_database", action="store_true",
        help="Verifica la base de Paper Trading configurada oficialmente (settings.paper_trading.database_path).",
    )
    verify_parser.add_argument(
        "--full", action="store_true",
        help="Usa PRAGMA integrity_check en vez de quick_check (más lento, más exhaustivo).",
    )

    restore_parser = subparsers.add_parser(
        "restore", parents=[common],
        help="Restaura un backup sobre la base de Paper Trading configurada (destructivo, requiere --confirm).",
    )
    restore_parser.add_argument("--backup-path", dest="backup_path", required=True, help="Ruta del backup a restaurar.")
    restore_parser.add_argument(
        "--confirm", action="store_true",
        help="Obligatorio: autoriza el reemplazo de la base configurada.",
    )
    restore_parser.add_argument(
        "--no-pre-restore-backup", dest="no_pre_restore_backup", action="store_true",
        help=(
            "Deshabilita el backup automático de la base configurada antes de restaurar "
            "(reduce la capacidad de recuperación ante un error)."
        ),
    )

    return parser


# --------------------------------------------------------------------------
# Ejecución de subcomandos
# --------------------------------------------------------------------------

def _run_backup(args: argparse.Namespace) -> Any:
    settings = _load_settings()
    service = SQLitePaperTradingBackupService(settings.paper_trading.database_path)
    return service.create_backup(args.output, overwrite=args.overwrite)


def _run_verify(args: argparse.Namespace) -> Any:
    if args.configured_database:
        settings = _load_settings()
        target_path = settings.paper_trading.database_path
    else:
        target_path = args.backup_path
    service = SQLitePaperTradingBackupService(target_path)
    return service.verify_database(target_path, full=args.full)


def _run_restore(args: argparse.Namespace) -> Any:
    settings = _load_settings()
    service = SQLitePaperTradingBackupService(settings.paper_trading.database_path)
    return service.restore_backup(args.backup_path, create_pre_restore_backup=not args.no_pre_restore_backup)


def _exit_code_for_verify(result: Any) -> int:
    if not result.integrity_ok:
        return EXIT_INTEGRITY_FAILED
    if not result.schema_ok:
        return EXIT_SCHEMA_INVALID
    return EXIT_OK


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_format = getattr(args, "format", "table")

    # §9/§14 (backup): sin --overwrite y sin destino ya existente, no se
    # exige --confirm; con --overwrite (o destino ya existente sin
    # --overwrite, que de todas formas fallará de forma controlada en el
    # servicio), la confirmación se valida antes de cualquier efecto.
    if args.command == "backup":
        destination_exists = Path(args.output).expanduser().exists()
        if destination_exists and args.overwrite and not args.confirm:
            print(_CONFIRMATION_MESSAGE, file=sys.stderr)
            return EXIT_CONFIRMATION_REQUIRED

    # §39 (restore): --confirm es obligatorio siempre, validado antes de
    # cargar configuración, antes de crear el backup previo, antes de
    # abrir el destino para escritura.
    if args.command == "restore" and not args.confirm:
        print(_CONFIRMATION_MESSAGE, file=sys.stderr)
        return EXIT_CONFIRMATION_REQUIRED

    try:
        if args.command == "backup":
            result = _run_backup(args)
        elif args.command == "verify":
            result = _run_verify(args)
        else:
            result = _run_restore(args)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except BackupSourceNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_NOT_FOUND
    except (BackupDestinationExistsError, BackupPathConflictError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_PATH_CONFLICT
    except BackupIntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INTEGRITY_FAILED
    except BackupSchemaError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_SCHEMA_INVALID
    except DatabaseBusyError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DATABASE_BUSY
    except (RestoreError, PaperTradingBackupError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    except Exception:
        print(_UNEXPECTED_MESSAGE, file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR

    _print_result(result, output_format)

    if args.command == "verify":
        return _exit_code_for_verify(result)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
