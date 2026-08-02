"""
Pruebas para src/paper_trading/reconciliation_cli.py (Etapa 6.8,
endurecida en la Etapa 6.22 con un contrato seguro de errores).

Nunca llama a `main()`/`_build_context()` contra la configuración real
(`load_settings()`/`data/crypto_data.db`): construye su propio
`PaperTradingContext` con `SQLitePaperTradingRepository` real sobre
`tmp_path`, y monkeypatchea `_build_context` para inyectarlo.
"""

import ast
import subprocess
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading import reconciliation_cli
from src.paper_trading.application import PaperTradingDisabledError
from src.paper_trading.composition import build_paper_trading_context
from src.paper_trading.exceptions import ReconciliationAuditError, ReconciliationConflictError
from src.paper_trading.models import CashBalance
from src.utils.config import PaperTradingConfig


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    def __init__(self):
        self._counter = 0

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def new_order_id(self) -> str:
        return self._next("order")

    def new_execution_id(self) -> str:
        return self._next("exec")

    def new_trade_id(self) -> str:
        return self._next("trade")

    def new_reconciliation_audit_id(self) -> str:
        return self._next("audit")


class _UnusedPriceProvider:
    def get_current_price(self, exchange, symbol):
        raise NotImplementedError

    def get_current_prices(self, symbols):
        raise NotImplementedError


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _config(tmp_path, enabled: bool = True) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=enabled, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"), rules_version="v1",
    )


def _context(tmp_path, enabled: bool = True):
    return build_paper_trading_context(
        config=_config(tmp_path, enabled=enabled), clock=FixedClock(_now()),
        id_generator=DeterministicIdGenerator(), market_price_provider=_UnusedPriceProvider(),
    )


def _patch_context(monkeypatch, context):
    monkeypatch.setattr(reconciliation_cli, "_build_context", lambda: context)


class TestInspectCommand:
    def test_inspect_on_clean_account_exits_zero(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "Consistente: s" in output

    def test_inspect_with_critical_issue_exits_one(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        context.repository.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == 1
        output = capsys.readouterr().out
        assert "ORPHAN_CASH_RESERVATION" in output

    def test_inspect_never_writes(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        context.repository.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        _patch_context(monkeypatch, context)
        reconciliation_cli.main(["inspect"])
        assert context.repository.get_cash_balance("USDT").reserved_balance == Decimal("999")


class TestRepairCommand:
    def test_repair_without_apply_is_dry_run_and_does_not_write(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        context.repository.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair"])
        assert exit_code == 0
        assert context.repository.get_cash_balance("USDT").reserved_balance == Decimal("999")
        output = capsys.readouterr().out
        assert "DRY-RUN" in output

    def test_repair_with_apply_writes(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        context.repository.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply"])
        assert exit_code == 0
        assert context.repository.get_cash_balance("USDT").reserved_balance == Decimal("0")

    def test_repair_with_issue_code_filter(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        context.repository.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main([
            "repair", "--apply", "--issue-code", "CASH_RESERVED_BALANCE_MISMATCH",
        ])
        assert exit_code == 0

    def test_repair_unsupported_issue_code_is_a_controlled_error(self, tmp_path, monkeypatch, capsys):
        """Etapa 6.22: UnsupportedRepairError ya no escapa como
        traceback -- se traduce a código 6, mensaje seguro en stderr,
        stdout vacío."""
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply", "--issue-code", "FILLED_ORDER_WITHOUT_EXECUTION"])
        assert exit_code == reconciliation_cli.EXIT_BUSINESS_REJECTED == 6
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "FILLED_ORDER_WITHOUT_EXECUTION" in captured.err
        assert "Traceback" not in captured.err


class TestIsolation:
    @staticmethod
    def _import_lines():
        source = open(reconciliation_cli.__file__, encoding="utf-8").read()
        return [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]

    def test_module_does_not_import_dashboard(self):
        assert not any("dashboard" in line.lower() for line in self._import_lines())

    def test_module_does_not_import_binance_or_requests(self):
        lines = self._import_lines()
        assert not any("binance" in line.lower() for line in lines)
        assert not any(line.strip() in ("import requests", "from requests") for line in lines)

    def test_module_does_not_import_schedule(self):
        assert not any("schedule" in line.lower() for line in self._import_lines())


class TestStructuralIsolation:
    """Etapa 6.22, §25: aislamiento verificado con `ast`, no búsqueda
    textual frágil -- confirma que el endurecimiento de errores no
    introdujo `traceback`/`pdb`/transportes/motores no requeridos."""

    _FORBIDDEN_MODULES = {
        "traceback", "pdb", "dashboard",
        "telegram_transport", "slack_transport", "email_transport", "webhook_transport",
        "notification_channels", "alert_delivery_service",
        "risk_engine", "fill_engine", "position_engine", "pnl_engine", "reservation_engine",
        "service", "inspection_job", "inspection_scheduler",
    }

    @staticmethod
    def _tree():
        source = open(reconciliation_cli.__file__, encoding="utf-8").read()
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
        source = open(reconciliation_cli.__file__, encoding="utf-8").read()
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

        monkeypatch.setattr(reconciliation_cli, "load_settings", _fail)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == reconciliation_cli.EXIT_CONFIG_ERROR == 3
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert "Traceback" not in captured.err


class TestDisabledDefenseInDepth:
    """`PaperTradingDisabledError` es inalcanzable hoy vía el código real
    (inspect_reconciliation()/repair_reconciliation() no gatean con
    _require_enabled(), §22.11) -- se prueba como defensa en
    profundidad, monkeypencheando directamente el método de
    Application, igual que se documenta en el propio módulo."""

    def test_disabled_error_from_application_exits_4(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _fail():
            raise PaperTradingDisabledError("Paper Trading está deshabilitado.")

        context.application.inspect_reconciliation = _fail
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == reconciliation_cli.EXIT_DISABLED == 4
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Paper Trading is disabled in configuration."

    def test_enabled_false_has_no_effect_in_practice(self, tmp_path, monkeypatch, capsys):
        """Caracterización (§10 del ticket): con la arquitectura real,
        enabled=false no cambia el comportamiento de reconciliation_cli.py."""
        context = _context(tmp_path, enabled=False)
        assert context.config.enabled is False
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == 0
        assert capsys.readouterr().err == ""


class TestDatabaseErrorHandling:
    def test_sqlite_error_during_repair_exits_5(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _fail(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        context.application.repair_reconciliation = _fail
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply"])
        assert exit_code == reconciliation_cli.EXIT_DATABASE_ERROR == 5
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() != ""
        assert "database is locked" not in captured.err
        assert "Traceback" not in captured.err


class TestBusinessRejectionHandling:
    def test_unsupported_repair_error_exits_6_with_safe_message(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply", "--issue-code", "FILLED_ORDER_WITHOUT_EXECUTION"])
        assert exit_code == reconciliation_cli.EXIT_BUSINESS_REJECTED == 6
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Traceback" not in captured.err

    def test_reconciliation_conflict_error_exits_6_with_safe_message(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _fail(*args, **kwargs):
            raise ReconciliationConflictError(
                "CashBalance(USDT).reserved_balance cambió entre el análisis y la reparación; "
                "vuelva a inspeccionar antes de reintentar."
            )

        context.application.repair_reconciliation = _fail
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply"])
        assert exit_code == reconciliation_cli.EXIT_BUSINESS_REJECTED == 6
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "reserved_balance" in captured.err
        assert "Traceback" not in captured.err


class TestOperationalErrorHandling:
    def test_reconciliation_audit_error_exits_7_without_leaking_wrapped_message(self, tmp_path, monkeypatch, capsys):
        """ReconciliationAuditError embebe el texto de la excepción
        original (potencialmente insegura) -- nunca debe imprimirse
        directamente."""
        context = _context(tmp_path)

        def _fail(*args, **kwargs):
            raise ReconciliationAuditError(
                "La reparación falló (sqlite3.OperationalError: database is locked at /secret/path.db) "
                "y además no se pudo registrar la auditoría del fallo."
            )

        context.application.repair_reconciliation = _fail
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply"])
        assert exit_code == reconciliation_cli.EXIT_OPERATIONAL_ERROR == 7
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "secret" not in captured.err
        assert "database is locked" not in captured.err
        assert "Traceback" not in captured.err

    def test_invalid_issue_code_value_error_exits_7(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply", "--issue-code", "NOT_A_REAL_CODE"])
        assert exit_code == reconciliation_cli.EXIT_OPERATIONAL_ERROR == 7
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Traceback" not in captured.err


class TestUnexpectedErrorHandling:
    def test_unexpected_exception_is_sanitized_and_exits_8(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _boom(*args, **kwargs):
            raise RuntimeError("boom with secret token=abc123")

        context.application.inspect_reconciliation = _boom
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == reconciliation_cli.EXIT_UNEXPECTED_ERROR == 8
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Reconciliation operation failed unexpectedly."
        assert "token=abc123" not in captured.err
        assert "Traceback" not in captured.err

    def test_injected_sensitive_message_never_leaks(self, tmp_path, monkeypatch, capsys):
        """§23 del ticket: excepción con ruta/SQL/secreto inyectados --
        nada de eso debe aparecer en la salida."""
        context = _context(tmp_path)
        sensitive = r"secret path C:\users\operator\paper.db SELECT * FROM cash_balances token=abc"

        def _boom(*args, **kwargs):
            raise RuntimeError(sensitive)

        context.application.repair_reconciliation = _boom
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["repair", "--apply"])
        assert exit_code == 8
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "secret path" not in captured.err
        assert "SELECT" not in captured.err
        assert "token=abc" not in captured.err
        assert "paper.db" not in captured.err
        assert "Traceback" not in captured.err


class TestKeyboardInterruptAndSystemExitNotCaptured:
    def test_keyboard_interrupt_propagates(self, tmp_path, monkeypatch):
        context = _context(tmp_path)

        def _interrupt(*args, **kwargs):
            raise KeyboardInterrupt()

        context.application.inspect_reconciliation = _interrupt
        _patch_context(monkeypatch, context)
        with pytest.raises(KeyboardInterrupt):
            reconciliation_cli.main(["inspect"])

    def test_system_exit_propagates(self, tmp_path, monkeypatch):
        context = _context(tmp_path)

        def _exit(*args, **kwargs):
            raise SystemExit(42)

        context.application.inspect_reconciliation = _exit
        _patch_context(monkeypatch, context)
        with pytest.raises(SystemExit) as exc_info:
            reconciliation_cli.main(["inspect"])
        assert exc_info.value.code == 42

    def test_argparse_error_still_exits_2(self):
        with pytest.raises(SystemExit) as exc_info:
            reconciliation_cli.main(["bogus-command"])
        assert exc_info.value.code == 2


class TestStdoutStderrSeparation:
    def test_success_never_writes_to_stderr(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = reconciliation_cli.main(["inspect"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out != ""

    def test_error_never_writes_to_stdout(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)

        def _boom(*args, **kwargs):
            raise RuntimeError("unexpected")

        context.application.inspect_reconciliation = _boom
        _patch_context(monkeypatch, context)
        reconciliation_cli.main(["inspect"])
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err != ""


class TestSubprocessHelp:
    def test_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.reconciliation_cli", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert "inspect" in result.stdout
        assert "repair" in result.stdout

    def test_subprocess_unsupported_repair_is_sanitized(self, tmp_path):
        """Reproduce el defecto original (§4 del ticket) vía subprocess
        real, con configuración inyectada por monkeypatch dentro del
        subproceso -- nunca contra config/config.yaml real."""
        repo = _repo_for_subprocess(tmp_path)
        code = f'''
import sys
sys.path.insert(0, r"{__import__("os").getcwd()}")
from decimal import Decimal
from types import SimpleNamespace
from src.paper_trading import reconciliation_cli
from src.utils.config import PaperTradingConfig
reconciliation_cli.load_settings = lambda: SimpleNamespace(paper_trading=PaperTradingConfig(
    enabled=True, database_path=r"{repo.db_path}", initial_capital=Decimal("10000"), currency="USDT",
    fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"), max_position_value=Decimal("100000"),
    rules_version="v1",
))
sys.exit(reconciliation_cli.main(["repair", "--apply", "--issue-code", "FILLED_ORDER_WITHOUT_EXECUTION"]))
'''
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 6
        assert result.stdout == ""
        assert "Traceback" not in result.stderr
        assert "reconciliation_service.py" not in result.stderr
        assert "application.py" not in result.stderr


def _repo_for_subprocess(tmp_path):
    from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
    repo = SQLitePaperTradingRepository(str(tmp_path / "subprocess_test.db"))
    repo.init()
    repo.save_cash_balance(CashBalance(
        currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
    ))
    return repo
