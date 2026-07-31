"""
Pruebas para src/paper_trading/backup_cli.py (Etapa 6.20).

Nunca llama a `main()` contra la configuración real
(`load_settings()`/`data/crypto_data.db`): monkeypatchea
`backup_cli.load_settings` para inyectar una ruta de base temporal
(`tmp_path`), mismo patrón que `test_paper_trading_order_cli.py`.
"""

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.paper_trading import backup_cli
from src.paper_trading.models import CashBalance
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed_db(path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(path))
    repo.init()
    repo.save_cash_balance(CashBalance(
        currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
    ))
    return repo


def _fake_settings(database_path: str):
    return SimpleNamespace(paper_trading=SimpleNamespace(database_path=str(database_path)))


def _patch_settings(monkeypatch, database_path):
    monkeypatch.setattr(backup_cli, "load_settings", lambda: _fake_settings(database_path))


# ==========================================================================
# Parser / --help
# ==========================================================================

class TestBuildParser:
    def test_main_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main(["--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "backup" in out and "verify" in out and "restore" in out

    def test_backup_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main(["backup", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--output" in out and "--overwrite" in out

    def test_verify_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main(["verify", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--backup-path" in out and "--configured-database" in out and "--full" in out

    def test_restore_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main(["restore", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--backup-path" in out and "--confirm" in out and "--no-pre-restore-backup" in out

    def test_missing_subcommand_exits_2(self):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main([])
        assert excinfo.value.code == 2

    def test_verify_requires_exactly_one_target(self):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main(["verify"])
        assert excinfo.value.code == 2

    def test_verify_rejects_both_targets(self, tmp_path):
        with pytest.raises(SystemExit) as excinfo:
            backup_cli.main([
                "verify", "--backup-path", str(tmp_path / "a.db"), "--configured-database",
            ])
        assert excinfo.value.code == 2


# ==========================================================================
# §9/§14/§40 -- backup: confirmación
# ==========================================================================

class TestBackupConfirmation:
    def test_backup_to_new_destination_needs_no_confirm(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        output = tmp_path / "new_backup.db"
        exit_code = backup_cli.main(["backup", "--output", str(output)])
        assert exit_code == 0
        assert output.exists()

    def test_overwrite_without_confirm_exits_5(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        output = tmp_path / "existing_backup.db"
        output.write_bytes(b"stale")

        exit_code = backup_cli.main(["backup", "--output", str(output), "--overwrite"])
        assert exit_code == 5
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "confirm" in captured.err.lower()
        assert output.read_bytes() == b"stale"

    def test_overwrite_without_confirm_leaves_no_temp_file(self, tmp_path, monkeypatch):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        output = tmp_path / "existing_backup.db"
        output.write_bytes(b"stale")
        backup_cli.main(["backup", "--output", str(output), "--overwrite"])

        assert list(tmp_path.glob(".paper_trading_backup_*")) == []

    def test_overwrite_with_confirm_succeeds(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        output = tmp_path / "existing_backup.db"
        output.write_bytes(b"stale")

        exit_code = backup_cli.main([
            "backup", "--output", str(output), "--overwrite", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["integrity_ok"] is True
        assert output.read_bytes() != b"stale"

    def test_existing_destination_without_overwrite_exits_6_without_confirm(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        output = tmp_path / "existing_backup.db"
        output.write_bytes(b"stale")

        exit_code = backup_cli.main(["backup", "--output", str(output)])
        assert exit_code == 6
        assert output.read_bytes() == b"stale"


class TestBackupOutcomes:
    def test_backup_source_missing_exits_4(self, tmp_path, monkeypatch, capsys):
        _patch_settings(monkeypatch, tmp_path / "missing.db")
        exit_code = backup_cli.main(["backup", "--output", str(tmp_path / "out.db")])
        assert exit_code == 4
        assert capsys.readouterr().err.strip() != ""

    def test_backup_table_output(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        exit_code = backup_cli.main(["backup", "--output", str(tmp_path / "out.db")])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "integrity_ok: true" in out
        assert "schema_ok: true" in out


# ==========================================================================
# §17/§27 -- --format antes/después del subcomando
# ==========================================================================

class TestFormatPosition:
    def test_format_json_after_subcommand(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        exit_code = backup_cli.main([
            "backup", "--output", str(tmp_path / "out.db"), "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_ok"] is True

    def test_format_json_before_subcommand(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        exit_code = backup_cli.main([
            "--format", "json", "backup", "--output", str(tmp_path / "out.db"),
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_ok"] is True

    def test_default_format_is_table(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        backup_cli.main(["backup", "--output", str(tmp_path / "out.db")])
        out = capsys.readouterr().out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


# ==========================================================================
# §15-18 -- verify
# ==========================================================================

class TestVerifyCommand:
    def test_verify_backup_path_valid(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        backup_cli.main(["backup", "--output", str(tmp_path / "out.db")])
        capsys.readouterr()

        exit_code = backup_cli.main(["verify", "--backup-path", str(tmp_path / "out.db"), "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["valid"] is True
        assert payload["check_type"] == "quick_check"

    def test_verify_full_uses_integrity_check(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        exit_code = backup_cli.main(["verify", "--backup-path", str(db), "--full", "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["check_type"] == "integrity_check"

    def test_verify_configured_database(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        exit_code = backup_cli.main(["verify", "--configured-database", "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["database_name"] == "pt.db"

    def test_verify_missing_backup_exits_4(self, tmp_path, capsys):
        exit_code = backup_cli.main(["verify", "--backup-path", str(tmp_path / "missing.db")])
        assert exit_code == 4

    def test_verify_corrupted_file_exits_7(self, tmp_path, capsys):
        corrupt = tmp_path / "corrupt.db"
        with open(corrupt, "wb") as f:
            f.write(b"\x00" * 32)
        exit_code = backup_cli.main(["verify", "--backup-path", str(corrupt), "--format", "json"])
        assert exit_code == 7
        payload = json.loads(capsys.readouterr().out)
        assert payload["valid"] is False
        assert payload["integrity_ok"] is False

    def test_verify_incomplete_schema_exits_8(self, tmp_path, capsys):
        import sqlite3
        db = tmp_path / "not_pt.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        exit_code = backup_cli.main(["verify", "--backup-path", str(db), "--format", "json"])
        assert exit_code == 8
        payload = json.loads(capsys.readouterr().out)
        assert payload["integrity_ok"] is True
        assert payload["schema_ok"] is False
        assert "paper_trading_orders" in payload["missing_tables"]

    def test_verify_never_writes(self, tmp_path):
        db = tmp_path / "pt.db"
        _seed_db(db)
        before = db.read_bytes()
        backup_cli.main(["verify", "--backup-path", str(db), "--full"])
        assert db.read_bytes() == before


# ==========================================================================
# §19-22/§39 -- restore
# ==========================================================================

class TestRestoreConfirmation:
    def test_restore_without_confirm_exits_5(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        before = db.read_bytes()

        exit_code = backup_cli.main(["restore", "--backup-path", str(tmp_path / "backup.db")])
        assert exit_code == 5
        captured = capsys.readouterr()
        assert captured.out == ""
        assert db.read_bytes() == before

    def test_restore_without_confirm_never_loads_settings(self, tmp_path, monkeypatch):
        def _fail():
            raise AssertionError("load_settings() must not be called without --confirm")
        monkeypatch.setattr(backup_cli, "load_settings", _fail)
        exit_code = backup_cli.main(["restore", "--backup-path", str(tmp_path / "backup.db")])
        assert exit_code == 5

    def test_restore_without_confirm_creates_no_pre_restore_backup(self, tmp_path, monkeypatch):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        backup_cli.main(["restore", "--backup-path", str(tmp_path / "backup.db")])
        assert list(tmp_path.glob("pt.pre_restore.*.db")) == []


class TestRestoreOutcomes:
    def test_restore_success(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        repo = _seed_db(db)
        _patch_settings(monkeypatch, db)

        backup_path = tmp_path / "backup.db"
        backup_cli.main(["backup", "--output", str(backup_path)])
        capsys.readouterr()

        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))

        exit_code = backup_cli.main([
            "restore", "--backup-path", str(backup_path), "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["restored"] is True
        assert payload["pre_restore_backup"] is not None

        restored_repo = SQLitePaperTradingRepository(str(db))
        assert restored_repo.get_cash_balance("USDT").total_balance == Decimal("10000")

    def test_restore_missing_backup_exits_4(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        before = db.read_bytes()

        exit_code = backup_cli.main([
            "restore", "--backup-path", str(tmp_path / "missing.db"), "--confirm",
        ])
        assert exit_code == 4
        assert db.read_bytes() == before

    def test_restore_corrupted_backup_exits_7(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        before = db.read_bytes()

        backup_path = tmp_path / "backup.db"
        backup_cli.main(["backup", "--output", str(backup_path)])
        with open(backup_path, "r+b") as f:
            f.seek(0)
            f.write(b"\x00" * 16)

        exit_code = backup_cli.main(["restore", "--backup-path", str(backup_path), "--confirm"])
        assert exit_code == 7
        assert db.read_bytes() == before

    def test_restore_invalid_schema_backup_exits_8(self, tmp_path, monkeypatch, capsys):
        import sqlite3
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        before = db.read_bytes()

        not_pt = tmp_path / "not_pt.db"
        conn = sqlite3.connect(str(not_pt))
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        exit_code = backup_cli.main(["restore", "--backup-path", str(not_pt), "--confirm"])
        assert exit_code == 8
        assert db.read_bytes() == before

    def test_restore_backup_equals_destination_exits_6(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        exit_code = backup_cli.main(["restore", "--backup-path", str(db), "--confirm"])
        assert exit_code == 6

    def test_restore_no_pre_restore_backup_flag(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        backup_path = tmp_path / "backup.db"
        backup_cli.main(["backup", "--output", str(backup_path)])
        capsys.readouterr()

        exit_code = backup_cli.main([
            "restore", "--backup-path", str(backup_path), "--confirm",
            "--no-pre-restore-backup", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["pre_restore_backup"] is None
        assert list(tmp_path.glob("pt.pre_restore.*.db")) == []

    def test_restore_busy_destination_exits_9(self, tmp_path, monkeypatch, capsys):
        import sqlite3
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)
        before = db.read_bytes()

        backup_path = tmp_path / "backup.db"
        backup_cli.main(["backup", "--output", str(backup_path)])
        capsys.readouterr()

        blocker = sqlite3.connect(str(db), timeout=5.0)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            exit_code = backup_cli.main(["restore", "--backup-path", str(backup_path), "--confirm"])
            assert exit_code == 9
        finally:
            blocker.rollback()
            blocker.close()
        assert db.read_bytes() == before


# ==========================================================================
# Etapa 6.20.1, §13 -- endurecimiento de publicación/verificación final
# ==========================================================================

class TestBackupSchemaHardening:
    def test_backup_with_invalid_schema_source_exits_8(self, tmp_path, monkeypatch, capsys):
        import sqlite3
        db = tmp_path / "not_pt.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        _patch_settings(monkeypatch, db)

        output = tmp_path / "out.db"
        exit_code = backup_cli.main(["backup", "--output", str(output)])

        assert exit_code == 8
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert str(tmp_path) not in captured.err
        assert not output.exists()


class TestRestoreFinalVerificationHardening:
    def test_restore_final_verification_failure_exits_10_not_0(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace as _SimpleNamespace
        from src.paper_trading.sqlite_backup import SQLitePaperTradingBackupService, VerificationResult
        from pathlib import Path

        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        backup_path = tmp_path / "backup.db"
        backup_cli.main(["backup", "--output", str(backup_path)])
        capsys.readouterr()

        real_check = SQLitePaperTradingBackupService._check
        target = Path(str(db)).expanduser().resolve()

        def fake_check(self, path, *, full):
            if not full and Path(path).resolve() == target:
                return VerificationResult(
                    valid=False, integrity_ok=False, schema_ok=True,
                    missing_tables=(), check_type="quick_check", database_name=Path(path).name,
                )
            return real_check(self, path, full=full)

        monkeypatch.setattr(SQLitePaperTradingBackupService, "_check", fake_check)

        exit_code = backup_cli.main(["restore", "--backup-path", str(backup_path), "--confirm"])

        assert exit_code == 10
        assert exit_code != 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert str(tmp_path) not in captured.err


# ==========================================================================
# §41 -- Subprocess
# ==========================================================================

class TestSubprocess:
    def test_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.backup_cli", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert "backup" in result.stdout

    def test_backup_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.backup_cli", "backup", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0

    def test_verify_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.backup_cli", "verify", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0

    def test_restore_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.backup_cli", "restore", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0

    def test_restore_without_confirm_via_subprocess_is_safe(self):
        """Sin --confirm, restore nunca carga configuración ni escribe --
        seguro incluso contra la config/base reales del repositorio."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.paper_trading.backup_cli", "restore",
                "--backup-path", "does-not-matter.db",
            ],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 5
        assert result.stdout == ""
        assert "confirm" in result.stderr.lower()


# ==========================================================================
# §42 -- Aislamiento estructural (AST)
# ==========================================================================

class TestStructuralIsolation:
    _FORBIDDEN_NAMES = {
        "PaperTradingApplication", "PaperTradingService", "RiskEngine", "FillEngine",
        "PositionEngine", "PnLEngine", "ReservationEngine",
    }
    _FORBIDDEN_MODULES = {"notification_channels", "dashboard"}
    _FORBIDDEN_MODULE_SUFFIXES = ("_transport",)

    @staticmethod
    def _tree():
        source = open(backup_cli.__file__, encoding="utf-8").read()
        return ast.parse(source)

    def test_does_not_import_forbidden_names(self):
        imported_names = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)
        overlap = imported_names & self._FORBIDDEN_NAMES
        assert not overlap, f"forbidden names imported: {overlap}"

    def test_does_not_import_forbidden_modules_or_transports(self):
        modules = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[-1])
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[-1])
        overlap = modules & self._FORBIDDEN_MODULES
        assert not overlap, f"forbidden modules imported: {overlap}"
        assert not any(module.endswith(self._FORBIDDEN_MODULE_SUFFIXES) for module in modules)

    def test_imports_sqlite_backup(self):
        modules = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[-1])
        assert "sqlite_backup" in modules


# ==========================================================================
# Seguridad -- sin traceback, sin str(exc) crudo en errores inesperados
# ==========================================================================

class TestUnexpectedErrorHandling:
    def test_unexpected_exception_is_sanitized(self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "pt.db"
        _seed_db(db)
        _patch_settings(monkeypatch, db)

        def _boom(*args, **kwargs):
            raise RuntimeError("unexpected internal detail")

        monkeypatch.setattr(backup_cli, "_run_backup", _boom)
        exit_code = backup_cli.main(["backup", "--output", str(tmp_path / "out.db")])
        assert exit_code == 11
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "unexpected internal detail" not in captured.err
        assert "Traceback" not in captured.err
