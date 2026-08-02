"""
Pruebas para src/paper_trading/inspection_cli.py (Etapa 6.9, endurecida
en la Etapa 6.22 con un contrato seguro de errores).

Nunca llama a `main()`/`_build_context()` contra la configuración real:
construye su propio `PaperTradingContext` sobre `tmp_path` y
monkeypatchea `_build_context`.
"""

import ast
import subprocess
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading import inspection_cli
from src.paper_trading.application import PaperTradingDisabledError
from src.paper_trading.composition import build_paper_trading_context
from src.paper_trading.exceptions import InspectionPersistenceError
from src.paper_trading.models import CashBalance
from src.utils.config import PaperTradingConfig, ReconciliationInspectionConfig


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    def __init__(self):
        self._n = 0

    def _next(self, prefix):
        self._n += 1
        return f"{prefix}-{self._n}"

    def new_order_id(self): return self._next("order")
    def new_execution_id(self): return self._next("exec")
    def new_trade_id(self): return self._next("trade")
    def new_reconciliation_audit_id(self): return self._next("audit")
    def new_inspection_run_id(self): return self._next("run")
    def new_inspection_alert_id(self): return self._next("alert")


class _UnusedPriceProvider:
    def get_current_price(self, exchange, symbol):
        raise NotImplementedError

    def get_current_prices(self, symbols):
        raise NotImplementedError


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _config(tmp_path, deliver_alerts=True, enabled=True) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=enabled, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"), rules_version="v1",
        reconciliation_inspection=ReconciliationInspectionConfig(deliver_alerts=deliver_alerts),
    )


def _context(tmp_path, deliver_alerts=True, enabled=True):
    return build_paper_trading_context(
        config=_config(tmp_path, deliver_alerts=deliver_alerts, enabled=enabled), clock=FixedClock(_now()),
        id_generator=DeterministicIdGenerator(), market_price_provider=_UnusedPriceProvider(),
    )


def _patch_context(monkeypatch, context):
    monkeypatch.setattr(inspection_cli, "_build_context", lambda: context)


class TestRunCommand:
    def test_run_executes_inspection_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "Corrida:" in output

    def test_run_persists_result(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        history = context.repository.fetch_inspection_runs(limit=None)
        assert len(history) == 1

    def test_run_delivers_alerts_when_enabled(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, deliver_alerts=True)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        output = capsys.readouterr().out
        assert "Alertas entregadas" in output
        assert context.repository.fetch_pending_inspection_alerts() == []


class TestAlertsCommand:
    def test_alerts_delivers_pending(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, deliver_alerts=False)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        assert context.repository.fetch_pending_inspection_alerts() != []

        exit_code = inspection_cli.main(["alerts"])
        assert exit_code == 0
        assert context.repository.fetch_pending_inspection_alerts() == []
        output = capsys.readouterr().out
        assert "Alertas entregadas" in output


class TestHistoryCommand:
    def test_history_lists_runs_readonly(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        exit_code = inspection_cli.main(["history"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "Corrida:" in output

    def test_history_respects_limit(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        inspection_cli.main(["run"])
        result = inspection_cli._run_history(context, limit=1)
        assert result == 0

    def test_history_invalid_limit_raises_controlled_error(self, tmp_path, monkeypatch, capsys):
        """limit=0 no es un valor válido (mismo criterio que fetch_orders():
        ValueError explícito). Etapa 6.22: ya no escapa como traceback --
        se traduce a código 7, mensaje seguro en stderr, stdout vacío."""
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        capsys.readouterr()
        exit_code = inspection_cli.main(["history", "--limit", "0"])
        assert exit_code == inspection_cli.EXIT_OPERATIONAL_ERROR == 7
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert "Traceback" not in captured.err

    def test_history_empty_reports_gracefully(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["history"])
        assert exit_code == 0
        assert "Sin corridas" in capsys.readouterr().out

    def test_history_does_not_write(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        before = context.repository.fetch_inspection_runs(limit=None)
        inspection_cli.main(["history"])
        after = context.repository.fetch_inspection_runs(limit=None)
        assert before == after


class TestConfigDisabled:
    def test_manual_run_works_even_if_scheduler_config_disabled(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        assert context.config.reconciliation_inspection.enabled is False
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == 0


class TestIsolation:
    @staticmethod
    def _import_lines():
        source = open(inspection_cli.__file__, encoding="utf-8").read()
        return [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]

    def test_module_does_not_import_dashboard(self):
        assert not any("dashboard" in line.lower() for line in self._import_lines())

    def test_module_does_not_import_binance(self):
        assert not any("binance" in line.lower() for line in self._import_lines())

    def test_module_never_calls_repair(self):
        source = open(inspection_cli.__file__, encoding="utf-8").read()
        assert ".repair(" not in source
        assert "repair_reconciliation" not in source


class TestStructuralIsolation:
    """Etapa 6.22, §25: aislamiento verificado con `ast`, no búsqueda
    textual frágil -- confirma que el endurecimiento de errores no
    introdujo `traceback`/`pdb`/transportes/motores no requeridos."""

    _FORBIDDEN_MODULES = {
        "traceback", "pdb", "dashboard",
        "telegram_transport", "slack_transport", "email_transport", "webhook_transport",
        "notification_channels", "alert_delivery_service",
        "risk_engine", "fill_engine", "position_engine", "pnl_engine", "reservation_engine",
        "service", "reconciliation_service",
    }

    @staticmethod
    def _tree():
        source = open(inspection_cli.__file__, encoding="utf-8").read()
        return ast.parse(source)

    def _imported_modules(self):
        modules = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[-1])
        return modules

    def test_no_forbidden_modules_imported(self):
        overlap = self._imported_modules() & self._FORBIDDEN_MODULES
        assert not overlap, f"forbidden modules imported: {overlap}"

    def test_does_not_call_traceback_or_pdb_functions(self):
        source = open(inspection_cli.__file__, encoding="utf-8").read()
        assert "print_exc(" not in source
        assert "format_exc(" not in source
        assert "exc_info=True" not in source
        assert "pdb.set_trace" not in source

    def test_does_not_catch_base_exception(self):
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                names = (
                    {alias.id for alias in ast.walk(node.type) if isinstance(alias, ast.Name)}
                )
                assert "BaseException" not in names


# ==========================================================================
# Etapa 6.22 -- contrato seguro de errores
# ==========================================================================

class TestConfigurationErrorHandling:
    def test_invalid_configuration_exits_3(self, monkeypatch, capsys):
        def _fail():
            raise FileNotFoundError("config/config.yaml not found")

        monkeypatch.setattr(inspection_cli, "load_settings", _fail)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == inspection_cli.EXIT_CONFIG_ERROR == 3
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert "Traceback" not in captured.err


class TestDisabledDefenseInDepth:
    """`PaperTradingDisabledError` es inalcanzable hoy vía el código real
    (los casos de uso de inspección no gatean con _require_enabled(),
    §23.13 del diseño) -- se prueba como defensa en profundidad,
    monkeypencheando directamente el método de Application, igual que
    se documenta en el propio módulo."""

    def test_disabled_error_from_application_exits_4(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _fail():
            raise PaperTradingDisabledError("Paper Trading está deshabilitado.")

        context.application.run_reconciliation_inspection = _fail
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == inspection_cli.EXIT_DISABLED == 4
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Paper Trading is disabled in configuration."

    def test_enabled_false_has_no_effect_in_practice(self, tmp_path, monkeypatch, capsys):
        """Caracterización (§10 del ticket): con la arquitectura real,
        enabled=false no cambia el comportamiento de inspection_cli.py."""
        context = _context(tmp_path, enabled=False)
        assert context.config.enabled is False
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == 0
        assert capsys.readouterr().err == ""


class TestDatabaseErrorHandling:
    def test_sqlite_error_during_run_exits_5(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _fail():
            raise sqlite3.OperationalError("database is locked")

        context.application.run_reconciliation_inspection = _fail
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == inspection_cli.EXIT_DATABASE_ERROR == 5
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert "database is locked" not in captured.err
        assert "Traceback" not in captured.err


class TestOperationalErrorHandling:
    def test_inspection_persistence_error_exits_7_without_leaking_wrapped_message(
        self, tmp_path, monkeypatch, capsys,
    ):
        """InspectionPersistenceError embebe el texto de la excepción
        original (potencialmente insegura) -- nunca debe imprimirse
        directamente."""
        context = _context(tmp_path)

        def _fail():
            raise InspectionPersistenceError(
                "No se pudo persistir la corrida run-1: sqlite3.OperationalError: "
                "database is locked at /secret/path.db"
            )

        context.application.run_reconciliation_inspection = _fail
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == inspection_cli.EXIT_OPERATIONAL_ERROR == 7
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "secret" not in captured.err
        assert "database is locked" not in captured.err
        assert "Traceback" not in captured.err

    def test_invalid_history_limit_value_error_exits_7(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["history", "--limit", "-1"])
        assert exit_code == inspection_cli.EXIT_OPERATIONAL_ERROR == 7
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Traceback" not in captured.err


class TestUnexpectedErrorHandling:
    def test_unexpected_exception_is_sanitized_and_exits_8(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _boom():
            raise RuntimeError("boom with secret token=abc123")

        context.application.run_reconciliation_inspection = _boom
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == inspection_cli.EXIT_UNEXPECTED_ERROR == 8
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Inspection operation failed unexpectedly."
        assert "token=abc123" not in captured.err
        assert "Traceback" not in captured.err

    def test_injected_sensitive_message_never_leaks(self, tmp_path, monkeypatch, capsys):
        """§23 del ticket: excepción con ruta/SQL/secreto inyectados --
        nada de eso debe aparecer en la salida."""
        context = _context(tmp_path)
        sensitive = r"sqlite error at C:\secret\paper.db executing SELECT * FROM cash_balances token=abc"

        def _boom():
            raise RuntimeError(sensitive)

        context.application.run_reconciliation_inspection = _boom
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == 8
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "sqlite error" not in captured.err
        assert "SELECT" not in captured.err
        assert "token=abc" not in captured.err
        assert "paper.db" not in captured.err
        assert "Traceback" not in captured.err


class TestKeyboardInterruptAndSystemExitNotCaptured:
    def test_keyboard_interrupt_propagates(self, tmp_path, monkeypatch):
        context = _context(tmp_path)

        def _interrupt():
            raise KeyboardInterrupt()

        context.application.run_reconciliation_inspection = _interrupt
        _patch_context(monkeypatch, context)
        with pytest.raises(KeyboardInterrupt):
            inspection_cli.main(["run"])

    def test_system_exit_propagates(self, tmp_path, monkeypatch):
        context = _context(tmp_path)

        def _exit():
            raise SystemExit(42)

        context.application.run_reconciliation_inspection = _exit
        _patch_context(monkeypatch, context)
        with pytest.raises(SystemExit) as exc_info:
            inspection_cli.main(["run"])
        assert exc_info.value.code == 42

    def test_argparse_error_still_exits_2(self):
        with pytest.raises(SystemExit) as exc_info:
            inspection_cli.main(["bogus-command"])
        assert exc_info.value.code == 2


class TestStdoutStderrSeparation:
    def test_success_never_writes_to_stderr(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = inspection_cli.main(["run"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out != ""

    def test_error_never_writes_to_stdout(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _boom():
            raise RuntimeError("unexpected")

        context.application.run_reconciliation_inspection = _boom
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err != ""


class TestSubprocessHelp:
    def test_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.inspection_cli", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert "run" in result.stdout
        assert "history" in result.stdout

    def test_subprocess_unexpected_error_is_sanitized(self, tmp_path):
        """Reproduce el defecto original (§4 del ticket) vía subprocess
        real: una excepción inesperada con datos sensibles inyectados no
        debe escapar como traceback."""
        repo = _repo_for_subprocess(tmp_path)
        code = f'''
import sys
sys.path.insert(0, r"{__import__("os").getcwd()}")
from decimal import Decimal
from types import SimpleNamespace
from src.paper_trading import inspection_cli
from src.utils.config import PaperTradingConfig
inspection_cli.load_settings = lambda: SimpleNamespace(paper_trading=PaperTradingConfig(
    enabled=True, database_path=r"{repo.db_path}", initial_capital=Decimal("10000"), currency="USDT",
    fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"), max_position_value=Decimal("100000"),
    rules_version="v1",
))
context = inspection_cli._build_context()
def _boom():
    raise RuntimeError(r"sqlite error at C:\\secret\\paper.db executing SELECT * FROM cash_balances token=abc")
context.application.run_reconciliation_inspection = _boom
inspection_cli._build_context = lambda: context
sys.exit(inspection_cli.main(["run"]))
'''
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 8
        assert result.stdout == ""
        assert "Traceback" not in result.stderr
        assert "secret" not in result.stderr
        assert "SELECT" not in result.stderr
        assert "token=abc" not in result.stderr


def _repo_for_subprocess(tmp_path):
    from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
    repo = SQLitePaperTradingRepository(str(tmp_path / "subprocess_test.db"))
    repo.init()
    repo.save_cash_balance(CashBalance(
        currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
    ))
    return repo
