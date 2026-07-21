"""
Pruebas para src/paper_trading/reconciliation_cli.py (Etapa 6.8).

Nunca llama a `main()`/`_build_context()` contra la configuración real
(`load_settings()`/`data/crypto_data.db`): construye su propio
`PaperTradingContext` con `SQLitePaperTradingRepository` real sobre
`tmp_path`, y monkeypatchea `_build_context` para inyectarlo.
"""

from datetime import datetime, timezone
from decimal import Decimal

from src.paper_trading import reconciliation_cli
from src.paper_trading.composition import build_paper_trading_context
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


def _config(tmp_path) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=True, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"), rules_version="v1",
    )


def _context(tmp_path):
    return build_paper_trading_context(
        config=_config(tmp_path), clock=FixedClock(_now()),
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

    def test_repair_unsupported_issue_code_is_a_controlled_error(self, tmp_path, monkeypatch):
        import pytest
        from src.paper_trading.exceptions import UnsupportedRepairError

        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        with pytest.raises(UnsupportedRepairError):
            reconciliation_cli.main(["repair", "--apply", "--issue-code", "FILLED_ORDER_WITHOUT_EXECUTION"])


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
