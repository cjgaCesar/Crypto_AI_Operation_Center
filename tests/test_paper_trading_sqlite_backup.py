"""
Pruebas para src/paper_trading/sqlite_backup.py (Etapa 6.20).

Usa únicamente `tmp_path`: nunca la base real del proyecto
(`data/crypto_data.db`). Construye bases de Paper Trading reales con
`SQLitePaperTradingRepository` para las pruebas de consistencia/
restauración, y bytes crudos (`sqlite3`/manipulación de archivo) para
las pruebas de corrupción y schema incompleto.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderStatus, OrderType, OrderSource, PositionSide, TradeSide
from src.paper_trading.models import CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade
from src.paper_trading.sqlite_backup import (
    REQUIRED_PAPER_TRADING_TABLES,
    BackupDestinationExistsError,
    BackupIntegrityError,
    BackupPathConflictError,
    BackupSchemaError,
    BackupSourceNotFoundError,
    DatabaseBusyError,
    RestoreError,
    SQLitePaperTradingBackupService,
)
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed_full_repository(db_path: str) -> SQLitePaperTradingRepository:
    """Siembra CashBalance, una orden PENDING, una FILLED con su
    ejecución, una posición, un trade y ambos tipos de snapshot -- el
    conjunto de datos que las pruebas de consistencia (§33) comparan
    entre origen y backup."""
    repo = SQLitePaperTradingRepository(db_path)
    repo.init()
    repo.save_cash_balance(CashBalance(
        currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("500"), updated_at=_now(),
    ))
    repo.save_order(Order(
        id="order-pending", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
        created_at=_now(), updated_at=_now(),
        reserved_price=Decimal("50000"), reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
    ))
    repo.save_order(Order(
        id="order-filled", exchange="Binance", symbol="ETHUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("1"), filled_quantity=Decimal("1"), average_fill_price=Decimal("2000"),
        status=OrderStatus.FILLED, source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    ))
    repo.save_execution(Execution(
        id="exec-1", order_id="order-filled", exchange="Binance", symbol="ETHUSDT",
        quantity=Decimal("1"), price=Decimal("2000"), fee=Decimal("2"), executed_at=_now(),
    ))
    repo.save_position(Position(
        exchange="Binance", symbol="ETHUSDT", side=PositionSide.LONG, quantity=Decimal("1"),
        average_entry_price=Decimal("2000"), updated_at=_now(),
    ))
    repo.save_trade(Trade(
        id="trade-1", exchange="Binance", symbol="ETHUSDT", side=TradeSide.LONG, quantity=Decimal("1"),
        entry_price=Decimal("2000"), exit_price=Decimal("2100"), gross_pnl=Decimal("100"),
        fees=Decimal("2"), net_pnl=Decimal("98"), opened_at=_now(), closed_at=_now(), exit_execution_id="exec-1",
    ))
    repo.save_portfolio_snapshot(PortfolioSnapshot(
        timestamp=_now(), cash_balance=Decimal("9500"), positions_value=Decimal("2000"),
        total_equity=Decimal("11500"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("98"),
    ))
    repo.save_pnl_snapshot(PnLSnapshot(
        timestamp=_now(), exchange="Binance", symbol="ETHUSDT", position_quantity=Decimal("1"),
        unrealized_pnl=Decimal("0"), realized_pnl_cumulative=Decimal("98"),
    ))
    return repo


def _table_snapshot(db_path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = sorted(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        return {table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    finally:
        conn.close()


def _corrupt_header(path) -> None:
    with open(path, "r+b") as f:
        f.seek(0)
        f.write(b"\x00" * 16)


# ==========================================================================
# §32 -- Pruebas unitarias del servicio: backup
# ==========================================================================

class TestCreateBackupBasic:
    def test_successful_backup(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"

        service = SQLitePaperTradingBackupService(str(source))
        result = service.create_backup(str(destination))

        assert destination.exists()
        assert result.source_name == "source.db"
        assert result.integrity_ok is True
        assert result.schema_ok is True
        assert result.size_bytes > 0
        assert result.created_at.tzinfo is not None

    def test_source_not_found(self, tmp_path):
        service = SQLitePaperTradingBackupService(str(tmp_path / "missing.db"))
        with pytest.raises(BackupSourceNotFoundError):
            service.create_backup(str(tmp_path / "backup.db"))
        assert not (tmp_path / "backup.db").exists()

    def test_destination_already_exists_without_overwrite(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"
        destination.write_bytes(b"pre-existing content")

        service = SQLitePaperTradingBackupService(str(source))
        with pytest.raises(BackupDestinationExistsError):
            service.create_backup(str(destination))
        assert destination.read_bytes() == b"pre-existing content"

    def test_overwrite_replaces_existing_destination(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"
        destination.write_bytes(b"stale backup")

        service = SQLitePaperTradingBackupService(str(source))
        result = service.create_backup(str(destination), overwrite=True)

        assert result.integrity_ok is True
        assert destination.read_bytes() != b"stale backup"

    def test_source_equals_destination_is_rejected(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        service = SQLitePaperTradingBackupService(str(source))
        with pytest.raises(BackupPathConflictError):
            service.create_backup(str(source), overwrite=True)

    def test_relative_path_destination_works(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        service = SQLitePaperTradingBackupService("source.db")
        result = service.create_backup("relative_backup.db")
        assert (tmp_path / "relative_backup.db").exists()
        assert result.destination == "relative_backup.db"

    def test_nonexistent_destination_directory_is_created(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "does_not_exist_yet" / "backup.db"
        service = SQLitePaperTradingBackupService(str(source))
        service.create_backup(str(destination))
        assert destination.exists()

    def test_destination_path_is_a_directory_is_rejected(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        directory = tmp_path / "a_directory"
        directory.mkdir()
        service = SQLitePaperTradingBackupService(str(source))
        with pytest.raises(ValueError):
            service.create_backup(str(directory))

    def test_empty_destination_path_is_rejected(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        service = SQLitePaperTradingBackupService(str(source))
        with pytest.raises(ValueError):
            service.create_backup("")

    def test_temp_file_is_cleaned_up_after_failed_backup(self, tmp_path):
        """Simula un fallo posterior a la copia (verificación fallida)
        provocando que el destino ya exista sin --overwrite -- en ese
        caso la validación aborta ANTES de crear ningún temporal, así
        que se confirma que no queda ningún archivo `.paper_trading_backup_*`
        huérfano en el directorio destino."""
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"
        destination.write_bytes(b"existing")

        service = SQLitePaperTradingBackupService(str(source))
        with pytest.raises(BackupDestinationExistsError):
            service.create_backup(str(destination))

        leftovers = list(tmp_path.glob(".paper_trading_backup_*"))
        assert leftovers == []

    def test_no_partial_backup_visible_after_source_disappears_mid_call(self, tmp_path, monkeypatch):
        """Fuerza un fallo dentro de `_copy_via_backup_api` (simulando
        una excepción de sqlite3) y confirma que no queda ningún
        temporal ni un backup parcial en el destino."""
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"

        service = SQLitePaperTradingBackupService(str(source))

        def _boom(self, *, source, destination):
            raise sqlite3.OperationalError("simulated failure mid-copy")

        monkeypatch.setattr(SQLitePaperTradingBackupService, "_copy_via_backup_api", _boom)

        with pytest.raises(BackupIntegrityError):
            service.create_backup(str(destination))

        assert not destination.exists()
        assert list(tmp_path.glob(".paper_trading_backup_*")) == []

    def test_atomic_publication_uses_os_replace(self, tmp_path, monkeypatch):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"

        calls = []
        real_replace = os.replace

        def _spy_replace(src, dst):
            calls.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _spy_replace)
        service = SQLitePaperTradingBackupService(str(source))
        service.create_backup(str(destination))

        assert len(calls) == 1
        assert calls[0][1] == str(destination)


# ==========================================================================
# §33 -- Consistencia origen vs. backup
# ==========================================================================

class TestBackupConsistency:
    def test_backup_matches_source_tables_and_rows(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"

        service = SQLitePaperTradingBackupService(str(source))
        service.create_backup(str(destination))

        source_snapshot = _table_snapshot(source)
        backup_snapshot = _table_snapshot(destination)
        assert REQUIRED_PAPER_TRADING_TABLES <= set(source_snapshot)
        assert source_snapshot == backup_snapshot

    def test_backup_passes_quick_check(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"
        service = SQLitePaperTradingBackupService(str(source))
        service.create_backup(str(destination))

        conn = sqlite3.connect(str(destination))
        try:
            assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        finally:
            conn.close()


# ==========================================================================
# §34 -- Backup con escritor concurrente
# ==========================================================================

class TestBackupWithConcurrentWriter:
    def test_backup_contains_only_committed_state(self, tmp_path):
        source = tmp_path / "source.db"
        _seed_full_repository(str(source))
        destination = tmp_path / "backup.db"

        barrier = threading.Barrier(2)
        backup_error = []
        backup_result = []

        def _writer():
            # La conexión se crea y se usa en este mismo hilo (sqlite3
            # rechaza compartir una conexión entre hilos por defecto).
            writer_conn = sqlite3.connect(str(source), timeout=5.0)
            barrier.wait()
            writer_conn.execute("BEGIN IMMEDIATE")
            writer_conn.execute(
                "INSERT INTO paper_trading_orders (id, exchange, symbol, side, order_type, quantity, status, "
                "filled_quantity, source, created_at, updated_at) VALUES "
                "('uncommitted-order', 'Binance', 'BTCUSDT', 'BUY', 'MARKET', '0.1', 'NEW', '0', 'MANUAL', "
                "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            time.sleep(0.2)  # mantiene la transacción abierta mientras corre el backup
            writer_conn.rollback()
            writer_conn.close()

        def _backup():
            barrier.wait()
            service = SQLitePaperTradingBackupService(str(source))
            try:
                backup_result.append(service.create_backup(str(destination)))
            except Exception as exc:  # pragma: no cover -- solo para diagnóstico si falla
                backup_error.append(exc)

        writer_thread = threading.Thread(target=_writer)
        backup_thread = threading.Thread(target=_backup)
        writer_thread.start()
        backup_thread.start()
        writer_thread.join(timeout=10)
        backup_thread.join(timeout=10)

        assert not backup_error, f"backup failed: {backup_error}"
        assert backup_result, "backup did not complete"

        backup_conn = sqlite3.connect(str(destination))
        try:
            ids = {row[0] for row in backup_conn.execute("SELECT id FROM paper_trading_orders")}
        finally:
            backup_conn.close()
        assert "uncommitted-order" not in ids
        assert {"order-pending", "order-filled"} <= ids


# ==========================================================================
# §32/§15-18 -- verify_database()
# ==========================================================================

class TestVerifyDatabase:
    def test_verify_valid_database_quick_check(self, tmp_path):
        db = tmp_path / "db.db"
        _seed_full_repository(str(db))
        service = SQLitePaperTradingBackupService(str(db))
        result = service.verify_database(str(db))
        assert result.valid is True
        assert result.check_type == "quick_check"
        assert result.missing_tables == ()

    def test_verify_valid_database_full_check(self, tmp_path):
        db = tmp_path / "db.db"
        _seed_full_repository(str(db))
        service = SQLitePaperTradingBackupService(str(db))
        result = service.verify_database(str(db), full=True)
        assert result.valid is True
        assert result.check_type == "integrity_check"

    def test_verify_nonexistent_database(self, tmp_path):
        service = SQLitePaperTradingBackupService(str(tmp_path / "missing.db"))
        with pytest.raises(BackupSourceNotFoundError):
            service.verify_database(str(tmp_path / "missing.db"))

    def test_verify_never_modifies_the_file(self, tmp_path):
        db = tmp_path / "db.db"
        _seed_full_repository(str(db))
        before = db.read_bytes()
        service = SQLitePaperTradingBackupService(str(db))
        service.verify_database(str(db), full=True)
        assert db.read_bytes() == before


class TestVerifyCorruptedDatabase:
    def test_corrupted_header_is_reported_invalid(self, tmp_path):
        db = tmp_path / "db.db"
        _seed_full_repository(str(db))
        before = db.read_bytes()
        _corrupt_header(db)

        service = SQLitePaperTradingBackupService(str(db))
        result = service.verify_database(str(db))

        assert result.valid is False
        assert result.integrity_ok is False
        assert db.read_bytes() != before  # confirmamos que corrompimos el archivo de prueba, no que verify lo tocó

    def test_verify_does_not_modify_corrupted_file_further(self, tmp_path):
        db = tmp_path / "db.db"
        _seed_full_repository(str(db))
        _corrupt_header(db)
        before = db.read_bytes()

        service = SQLitePaperTradingBackupService(str(db))
        service.verify_database(str(db))

        assert db.read_bytes() == before


class TestVerifyIncompleteSchema:
    def test_valid_sqlite_file_without_paper_trading_schema(self, tmp_path):
        db = tmp_path / "not_paper_trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE some_other_table (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        service = SQLitePaperTradingBackupService(str(db))
        result = service.verify_database(str(db))

        assert result.integrity_ok is True
        assert result.schema_ok is False
        assert result.valid is False
        assert set(result.missing_tables) == REQUIRED_PAPER_TRADING_TABLES

    def test_partial_schema_reports_only_missing_tables(self, tmp_path):
        db = tmp_path / "partial.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE paper_trading_orders (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE paper_trading_cash_balances (currency TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        service = SQLitePaperTradingBackupService(str(db))
        result = service.verify_database(str(db))

        assert result.schema_ok is False
        assert "paper_trading_orders" not in result.missing_tables
        assert "paper_trading_cash_balances" not in result.missing_tables
        assert "paper_trading_trades" in result.missing_tables


# ==========================================================================
# §37 -- Restauración exitosa
# ==========================================================================

class TestRestoreSuccess:
    def test_restore_returns_source_to_backup_state(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        repo = _seed_full_repository(str(original))
        backup_path = tmp_path / "backup.db"

        service = SQLitePaperTradingBackupService(str(original))
        service.create_backup(str(backup_path))

        # Modifica el original después del backup.
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        assert repo.get_cash_balance("USDT").total_balance == Decimal("1")

        result = service.restore_backup(str(backup_path))

        assert result.restored is True
        assert result.integrity_ok is True
        assert result.schema_ok is True
        restored_repo = SQLitePaperTradingRepository(str(original))
        assert restored_repo.get_cash_balance("USDT").total_balance == Decimal("10000")

    def test_restore_creates_pre_restore_backup_with_modified_state(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        repo = _seed_full_repository(str(original))
        backup_path = tmp_path / "backup.db"

        service = SQLitePaperTradingBackupService(str(original))
        service.create_backup(str(backup_path))

        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))

        result = service.restore_backup(str(backup_path))

        assert result.pre_restore_backup is not None
        pre_restore_files = list(tmp_path.glob("paper_trading.pre_restore.*.db"))
        assert len(pre_restore_files) == 1
        pre_restore_repo = SQLitePaperTradingRepository(str(pre_restore_files[0]))
        assert pre_restore_repo.get_cash_balance("USDT").total_balance == Decimal("1")

    def test_restore_without_pre_restore_backup(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        backup_path = tmp_path / "backup.db"
        service = SQLitePaperTradingBackupService(str(original))
        service.create_backup(str(backup_path))

        result = service.restore_backup(str(backup_path), create_pre_restore_backup=False)

        assert result.pre_restore_backup is None
        assert list(tmp_path.glob("paper_trading.pre_restore.*.db")) == []

    def test_restore_onto_nonexistent_destination_skips_pre_restore_backup(self, tmp_path):
        source_for_backup = tmp_path / "source_for_backup.db"
        _seed_full_repository(str(source_for_backup))
        backup_path = tmp_path / "backup.db"
        SQLitePaperTradingBackupService(str(source_for_backup)).create_backup(str(backup_path))

        destination = tmp_path / "brand_new.db"
        assert not destination.exists()
        service = SQLitePaperTradingBackupService(str(destination))
        result = service.restore_backup(str(backup_path))

        assert result.pre_restore_backup is None
        assert destination.exists()


# ==========================================================================
# §38 -- Restauración fallida (el destino original queda intacto)
# ==========================================================================

class TestRestoreFailure:
    def test_restore_with_nonexistent_backup(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        before = original.read_bytes()

        service = SQLitePaperTradingBackupService(str(original))
        with pytest.raises(BackupSourceNotFoundError):
            service.restore_backup(str(tmp_path / "does_not_exist.db"))

        assert original.read_bytes() == before

    def test_restore_with_corrupted_backup(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        before = original.read_bytes()

        backup_path = tmp_path / "backup.db"
        SQLitePaperTradingBackupService(str(original)).create_backup(str(backup_path))
        _corrupt_header(backup_path)

        service = SQLitePaperTradingBackupService(str(original))
        with pytest.raises(BackupIntegrityError):
            service.restore_backup(str(backup_path))

        assert original.read_bytes() == before

    def test_restore_with_invalid_schema_backup(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        before = original.read_bytes()

        not_paper_trading = tmp_path / "not_paper_trading.db"
        conn = sqlite3.connect(str(not_paper_trading))
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        service = SQLitePaperTradingBackupService(str(original))
        with pytest.raises(BackupSchemaError):
            service.restore_backup(str(not_paper_trading))

        assert original.read_bytes() == before

    def test_restore_onto_busy_destination(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        before = original.read_bytes()

        backup_path = tmp_path / "backup.db"
        SQLitePaperTradingBackupService(str(original)).create_backup(str(backup_path))

        blocker = sqlite3.connect(str(original), timeout=5.0)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            service = SQLitePaperTradingBackupService(str(original))
            with pytest.raises(DatabaseBusyError):
                service.restore_backup(str(backup_path))
        finally:
            blocker.rollback()
            blocker.close()

        assert original.read_bytes() == before

    def test_restore_backup_equals_destination_is_rejected(self, tmp_path):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        service = SQLitePaperTradingBackupService(str(original))
        with pytest.raises(BackupPathConflictError):
            service.restore_backup(str(original))

    def test_failure_before_replace_leaves_destination_intact(self, tmp_path, monkeypatch):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        before = original.read_bytes()

        backup_path = tmp_path / "backup.db"
        SQLitePaperTradingBackupService(str(original)).create_backup(str(backup_path))

        service = SQLitePaperTradingBackupService(str(original))

        original_copy_method = SQLitePaperTradingBackupService._copy_via_backup_api
        call_count = {"n": 0}

        def _fail_on_restore_copy(self, *, source, destination):
            call_count["n"] += 1
            if call_count["n"] == 2:  # 1st call = pre-restore backup, 2nd = restore copy itself
                raise sqlite3.OperationalError("simulated failure during restore copy")
            return original_copy_method(self, source=source, destination=destination)

        monkeypatch.setattr(SQLitePaperTradingBackupService, "_copy_via_backup_api", _fail_on_restore_copy)

        with pytest.raises(RestoreError):
            service.restore_backup(str(backup_path))

        assert original.read_bytes() == before

    def test_failure_during_pre_restore_backup_leaves_destination_intact(self, tmp_path, monkeypatch):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        before = original.read_bytes()

        backup_path = tmp_path / "backup.db"
        SQLitePaperTradingBackupService(str(original)).create_backup(str(backup_path))

        service = SQLitePaperTradingBackupService(str(original))

        def _fail(self, *, source, destination):
            raise sqlite3.OperationalError("simulated failure during pre-restore backup")

        monkeypatch.setattr(SQLitePaperTradingBackupService, "_copy_via_backup_api", _fail)

        with pytest.raises(BackupIntegrityError):
            service.restore_backup(str(backup_path))

        assert original.read_bytes() == before

    def test_no_leftover_temp_files_after_failed_restore(self, tmp_path, monkeypatch):
        original = tmp_path / "paper_trading.db"
        _seed_full_repository(str(original))
        backup_path = tmp_path / "backup.db"
        SQLitePaperTradingBackupService(str(original)).create_backup(str(backup_path))

        service = SQLitePaperTradingBackupService(str(original))

        def _fail(self, *, source, destination):
            raise sqlite3.OperationalError("simulated failure")

        monkeypatch.setattr(SQLitePaperTradingBackupService, "_copy_via_backup_api", _fail)

        with pytest.raises(RestoreError):
            service.restore_backup(str(backup_path), create_pre_restore_backup=False)

        assert list(tmp_path.glob(".paper_trading_restore_*")) == []
        assert list(tmp_path.glob(".paper_trading_backup_*")) == []


# ==========================================================================
# Timeout de constructor (mismo criterio que SQLitePaperTradingRepository)
# ==========================================================================

class TestConstructorValidation:
    def test_rejects_zero_timeout(self, tmp_path):
        with pytest.raises(ValueError):
            SQLitePaperTradingBackupService(str(tmp_path / "db.db"), timeout_seconds=0)

    def test_rejects_negative_timeout(self, tmp_path):
        with pytest.raises(ValueError):
            SQLitePaperTradingBackupService(str(tmp_path / "db.db"), timeout_seconds=-1)

    def test_rejects_nan_timeout(self, tmp_path):
        with pytest.raises(ValueError):
            SQLitePaperTradingBackupService(str(tmp_path / "db.db"), timeout_seconds=float("nan"))

    def test_rejects_bool_timeout(self, tmp_path):
        with pytest.raises(ValueError):
            SQLitePaperTradingBackupService(str(tmp_path / "db.db"), timeout_seconds=True)
