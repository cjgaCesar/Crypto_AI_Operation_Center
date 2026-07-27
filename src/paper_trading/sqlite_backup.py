"""
Servicio de backup, verificación y restauración de la base SQLite de
Paper Trading (Etapa 6.20).

Capa reutilizable e independiente de argparse (ver `backup_cli.py`,
que solo traduce línea de comandos <-> esta clase). No pertenece al
dominio de trading: deliberadamente separada de
`SQLitePaperTradingRepository`/`PaperTradingApplication`/
`PaperTradingService` -- nunca importa RiskEngine/FillEngine/
PositionEngine/PnLEngine/ReservationEngine/PaperTradingApplication ni
construye un `PaperTradingContext`. Solo necesita una ruta de archivo
SQLite, nunca `Settings`/`PaperTradingConfig` completos.

Método de backup: `sqlite3.Connection.backup()` (API de Backup Online
de SQLite) -- nunca `shutil.copy()`/`Path.read_bytes()` como mecanismo
principal, porque una copia de bytes cruda no garantiza consistencia
si existe un escritor con una transacción en curso. Verificado
empíricamente (Etapa 6.20): con un escritor manteniendo `BEGIN
IMMEDIATE` + una escritura sin `commit()`, una conexión de solo
lectura separada (`mode=ro`) sigue pudiendo copiar el último estado
*confirmado* sin bloquearse -- mismo comportamiento ya caracterizado
para lectores normales en la Etapa 6.17 (§32.2/§32.12 de
ARQUITECTURA_PAPER_TRADING.md). `shutil`/`os.replace()` solo se usan
para publicar un archivo temporal ya verificado y cerrado (§10 del
ticket).

Publicación atómica: cada operación que produce un archivo SQLite
nuevo (`create_backup()`, y el backup previo interno de
`restore_backup()`) escribe primero a un archivo temporal en el MISMO
directorio del destino (`tempfile.mkstemp(dir=...)`, para que
`os.replace()` sea atómico dentro del mismo filesystem), lo verifica
(`PRAGMA quick_check`), cierra todas las conexiones, y solo entonces
lo publica con `os.replace()`. Ante cualquier fallo antes de esa
publicación, el destino anterior (si existía) queda intacto y el
temporal se elimina -- nunca queda un backup parcial visible como
válido.

No habilita ni asume WAL (la Etapa 6.17 decidió no activarlo): la API
de backup no depende de copiar archivos `-wal`/`-shm`.
"""

import math
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_BACKUP_TIMEOUT_SECONDS = 5.0

# Las 11 tablas paper_trading_* que SQLitePaperTradingRepository.init()
# crea (Etapas 6.3/6.7/6.8/6.9/6.10.1) -- única definición de esta
# constante en todo el subsistema de backup (§17 del ticket: nunca
# codificada dos veces).
REQUIRED_PAPER_TRADING_TABLES = frozenset({
    "paper_trading_orders",
    "paper_trading_executions",
    "paper_trading_trades",
    "paper_trading_positions",
    "paper_trading_cash_balances",
    "paper_trading_portfolio_snapshots",
    "paper_trading_pnl_snapshots",
    "paper_trading_reconciliation_audit",
    "paper_trading_inspection_runs",
    "paper_trading_inspection_alerts",
    "paper_trading_inspection_alert_channel_deliveries",
})


# --------------------------------------------------------------------------
# Excepciones (subsistema propio, nunca mezclado con la jerarquía de
# dominio de órdenes en exceptions.py)
# --------------------------------------------------------------------------

class PaperTradingBackupError(Exception):
    """Error base del subsistema de backup/restore de Paper Trading."""


class BackupSourceNotFoundError(PaperTradingBackupError):
    """La base origen (para backup) o el archivo de backup (para verify/
    restore) no existe, no es un archivo, o no se puede leer."""


class BackupDestinationExistsError(PaperTradingBackupError):
    """El destino de un backup ya existe y no se pidió sobrescribir."""


class BackupPathConflictError(PaperTradingBackupError):
    """Origen y destino resuelven al mismo archivo."""


class BackupIntegrityError(PaperTradingBackupError):
    """Una base o backup no pasó `PRAGMA quick_check`/`integrity_check`."""


class BackupSchemaError(PaperTradingBackupError):
    """Una base o backup no tiene el schema mínimo de Paper Trading."""


class DatabaseBusyError(PaperTradingBackupError):
    """La base destino está bloqueada por otra conexión/proceso escritor."""


class RestoreError(PaperTradingBackupError):
    """Falló la restauración durante la copia o la verificación posterior
    (nunca después de `os.replace()`, ver `restore_backup()`)."""


# --------------------------------------------------------------------------
# Resultados (inmutables, sin objetos SQLite/Settings)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BackupResult:
    source_name: str
    destination: str
    created_at: datetime
    size_bytes: int
    integrity_ok: bool
    schema_ok: bool


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    integrity_ok: bool
    schema_ok: bool
    missing_tables: tuple
    check_type: str
    database_name: str


@dataclass(frozen=True)
class RestoreResult:
    restored: bool
    backup_path: str
    destination: str
    pre_restore_backup: Optional[str]
    integrity_ok: bool
    schema_ok: bool


# --------------------------------------------------------------------------
# Utilidades internas de rutas (§13/§31: nunca exponer una ruta absoluta
# completa que pueda ser sensible; preferir relativa al cwd o basename)
# --------------------------------------------------------------------------

def _safe_display(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        return path.name
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


class SQLitePaperTradingBackupService:
    """Backup, verificación y restauración de una base SQLite de Paper
    Trading. Solo necesita una ruta de archivo (`database_path`) --
    nunca `PaperTradingConfig`/`Settings` completos, nunca construye un
    `PaperTradingContext` ni instancia `SQLitePaperTradingRepository`."""

    def __init__(self, database_path: str, *, timeout_seconds: float = DEFAULT_BACKUP_TIMEOUT_SECONDS) -> None:
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("SQLite timeout must be a finite number greater than zero.")
        self._database_path = database_path
        self._timeout_seconds = timeout_seconds

    # --- backup --------------------------------------------------------

    def create_backup(self, destination_path: str, *, overwrite: bool = False) -> BackupResult:
        """Crea una copia consistente de la base configurada
        (`database_path`) en `destination_path`, vía
        `sqlite3.Connection.backup()`. Nunca llama `repo.init()`,
        migraciones ni `seed_initial_cash_balance()` -- si la base
        origen no existe, no se crea (`BackupSourceNotFoundError`)."""
        if not destination_path:
            raise ValueError("destination_path must not be empty.")
        source = Path(self._database_path).expanduser()
        destination = Path(destination_path).expanduser()
        return self._create_backup_internal(source, destination, overwrite=overwrite)

    def _create_backup_internal(self, source: Path, destination: Path, *, overwrite: bool) -> BackupResult:
        self._validate_backup_paths(source, destination, overwrite=overwrite)

        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(destination.parent), prefix=".paper_trading_backup_", suffix=".tmp",
        )
        os.close(tmp_fd)
        tmp_path: Optional[Path] = Path(tmp_name)
        try:
            try:
                self._copy_via_backup_api(source=source, destination=tmp_path)
            except sqlite3.DatabaseError:
                raise BackupIntegrityError("Backup failed while copying from the source database.") from None

            verification = self._check(tmp_path, full=False)
            if not verification.integrity_ok:
                raise BackupIntegrityError("Backup failed integrity verification before publishing.")

            os.replace(str(tmp_path), str(destination))
            published = tmp_path
            tmp_path = None  # ya publicado: no se borra en el finally

            return BackupResult(
                source_name=source.name,
                destination=_safe_display(destination),
                created_at=datetime.now(timezone.utc),
                size_bytes=destination.stat().st_size,
                integrity_ok=verification.integrity_ok,
                schema_ok=verification.schema_ok,
            )
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _validate_backup_paths(self, source: Path, destination: Path, *, overwrite: bool) -> None:
        if not source.exists():
            raise BackupSourceNotFoundError(f"Source database not found: {source.name}")
        if source.is_dir():
            raise BackupSourceNotFoundError(f"Source path is a directory, not a file: {source.name}")
        if destination.is_dir():
            raise ValueError("destination_path points to a directory, not a file.")
        if _same_file(source, destination):
            raise BackupPathConflictError("Source and destination must not resolve to the same file.")
        if destination.exists() and not overwrite:
            raise BackupDestinationExistsError(f"Destination already exists: {destination.name}")

    def _copy_via_backup_api(self, *, source: Path, destination: Path) -> None:
        """Único punto que llama `sqlite3.Connection.backup()` -- origen
        siempre abierto en modo real de solo lectura (`mode=ro`, nunca
        escribe ni crea el origen), destino como conexión normal sobre
        un archivo temporal ya creado."""
        source_conn = sqlite3.connect(
            f"file:{source.as_posix()}?mode=ro", uri=True, timeout=self._timeout_seconds,
        )
        try:
            dest_conn = sqlite3.connect(str(destination), timeout=self._timeout_seconds)
            try:
                source_conn.backup(dest_conn)
                dest_conn.commit()
            finally:
                dest_conn.close()
        finally:
            source_conn.close()

    # --- verify ----------------------------------------------------------

    def verify_database(self, database_path: str, *, full: bool = False) -> VerificationResult:
        """Verifica integridad física (`quick_check`/`integrity_check`) y
        schema mínimo de Paper Trading de un archivo SQLite cualquiera
        (base configurada o backup). Nunca lanza por un resultado
        inválido -- eso es responsabilidad de quien llama (`backup_cli.py`
        decide el código de salida; `create_backup()`/`restore_backup()`
        sí escalan a excepción, ver más abajo)."""
        path = Path(database_path).expanduser()
        if not path.exists():
            raise BackupSourceNotFoundError(f"Database not found: {path.name}")
        if path.is_dir():
            raise BackupSourceNotFoundError(f"Path is a directory, not a file: {path.name}")
        return self._check(path, full=full)

    def _check(self, path: Path, *, full: bool) -> VerificationResult:
        check_type = "integrity_check" if full else "quick_check"
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=self._timeout_seconds)
        try:
            try:
                rows = conn.execute(f"PRAGMA {check_type}").fetchall()
                integrity_ok = len(rows) == 1 and rows[0][0] == "ok"
            except sqlite3.DatabaseError:
                # Archivo que no es una base SQLite válida (header corrupto,
                # bytes aleatorios, etc.) -- resultado inválido, nunca una
                # excepción no controlada (§35 del ticket).
                integrity_ok = False

            if integrity_ok:
                existing_tables = {
                    row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                missing = tuple(sorted(REQUIRED_PAPER_TRADING_TABLES - existing_tables))
            else:
                missing = tuple(sorted(REQUIRED_PAPER_TRADING_TABLES))
        finally:
            conn.close()

        schema_ok = not missing
        return VerificationResult(
            valid=integrity_ok and schema_ok,
            integrity_ok=integrity_ok,
            schema_ok=schema_ok,
            missing_tables=missing,
            check_type=check_type,
            database_name=path.name,
        )

    # --- busy check (restore preflight, §23 del ticket) -------------------

    def _ensure_not_busy(self, path: Path) -> None:
        """Detecta un escritor activo con una prueba corta y controlada
        (`BEGIN IMMEDIATE` con `timeout=0` sobre una conexión propia,
        `ROLLBACK` inmediato si se adquiere) -- nunca deja una
        transacción abierta, nunca espera el timeout completo, nunca
        intenta cerrar procesos ajenos."""
        probe = sqlite3.connect(str(path), timeout=0)
        try:
            try:
                probe.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                raise DatabaseBusyError(
                    "Destination database appears to be in use by another process."
                ) from None
            else:
                probe.rollback()
        finally:
            probe.close()

    # --- restore -----------------------------------------------------------

    def restore_backup(self, backup_path: str, *, create_pre_restore_backup: bool = True) -> RestoreResult:
        """Restaura `backup_path` sobre la base configurada
        (`database_path`), con backup previo por defecto y publicación
        atómica. Nunca copia el backup directamente sobre el destino
        (§22 del ticket): backup previo -> copiar a temporal -> verificar
        -> `os.replace()` -> re-verificar el destino ya publicado."""
        backup = Path(backup_path).expanduser()
        destination = Path(self._database_path).expanduser()

        if not backup.exists():
            raise BackupSourceNotFoundError(f"Backup file not found: {backup.name}")
        if backup.is_dir():
            raise BackupSourceNotFoundError(f"Backup path is a directory, not a file: {backup.name}")

        backup_check = self._check(backup, full=True)
        if not backup_check.integrity_ok:
            raise BackupIntegrityError("Backup failed integrity verification; restore aborted.")
        if not backup_check.schema_ok:
            raise BackupSchemaError(
                f"Backup is missing required Paper Trading tables: {', '.join(backup_check.missing_tables)}"
            )

        if _same_file(backup, destination):
            raise BackupPathConflictError("Backup path and destination database must not be the same file.")

        if destination.exists():
            self._ensure_not_busy(destination)

        pre_restore_display: Optional[str] = None
        if create_pre_restore_backup and destination.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            pre_restore_path = destination.parent / f"{destination.stem}.pre_restore.{timestamp}{destination.suffix}"
            pre_restore_result = self._create_backup_internal(destination, pre_restore_path, overwrite=False)
            pre_restore_display = pre_restore_result.destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(destination.parent), prefix=".paper_trading_restore_", suffix=".tmp",
        )
        os.close(tmp_fd)
        tmp_path: Optional[Path] = Path(tmp_name)
        try:
            try:
                self._copy_via_backup_api(source=backup, destination=tmp_path)
            except sqlite3.DatabaseError:
                raise RestoreError("Restore failed while copying the backup.") from None

            post_copy_check = self._check(tmp_path, full=False)
            if not post_copy_check.integrity_ok or not post_copy_check.schema_ok:
                raise RestoreError("Restored temporary database failed post-copy verification.")

            # Publicación atómica: a partir de aquí, un fallo ya no puede
            # dejar el destino a medias -- os.replace() es la única
            # operación que toca el archivo destino final.
            os.replace(str(tmp_path), str(destination))
            tmp_path = None
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        final_check = self._check(destination, full=False)

        return RestoreResult(
            restored=True,
            backup_path=_safe_display(backup),
            destination=_safe_display(destination),
            pre_restore_backup=pre_restore_display,
            integrity_ok=final_check.integrity_ok,
            schema_ok=final_check.schema_ok,
        )
