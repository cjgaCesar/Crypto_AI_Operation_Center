"""
Pruebas para src/paper_trading/inspection_cli.py (Etapa 6.9).

Nunca llama a `main()`/`_build_context()` contra la configuración real:
construye su propio `PaperTradingContext` sobre `tmp_path` y
monkeypatchea `_build_context`.
"""

from datetime import datetime, timezone
from decimal import Decimal

from src.paper_trading import inspection_cli
from src.paper_trading.composition import build_paper_trading_context
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


def _config(tmp_path, deliver_alerts=True) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=True, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"), rules_version="v1",
        reconciliation_inspection=ReconciliationInspectionConfig(deliver_alerts=deliver_alerts),
    )


def _context(tmp_path, deliver_alerts=True):
    return build_paper_trading_context(
        config=_config(tmp_path, deliver_alerts=deliver_alerts), clock=FixedClock(_now()),
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

    def test_history_invalid_limit_raises_controlled_error(self, tmp_path, monkeypatch):
        """limit=0 no es un valor válido (mismo criterio que fetch_orders():
        ValueError explícito, nunca silenciado -- ver reconciliation_cli.py)."""
        import pytest

        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        inspection_cli.main(["run"])
        with pytest.raises(ValueError):
            inspection_cli.main(["history", "--limit", "0"])

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
