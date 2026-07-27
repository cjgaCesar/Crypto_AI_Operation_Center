"""
Pruebas para src/paper_trading/order_cli.py (Etapa 6.19, endurecido en
6.19.1 con el gate temprano de `paper_trading.enabled`).

Nunca llama a `main()` contra la configuración real
(`load_settings()`/`data/crypto_data.db`): monkeypatchea `_load_settings`
(para controlar `enabled` sin tocar `config/config.yaml`) y `_build_context`
(que ahora recibe `settings`, Etapa 6.19.1) para inyectar un
`PaperTradingContext` de prueba con `SQLitePaperTradingRepository` real
sobre `tmp_path` -- mismo patrón que
`test_paper_trading_reconciliation_cli.py`/
`test_paper_trading_inspection_cli.py`.

Dos categorías de prueba para `enabled=false`, deliberadamente separadas
(§21 de la Etapa 6.19.1):
- `TestApplicationDefenseInDepthWhenDisabled`: el contexto YA está
  construido (con `enabled=False` en su config) y se confirma que
  `PaperTradingApplication._require_enabled()` sigue protegiendo por su
  cuenta -- defensa de dominio, sin relación con el gate de la CLI.
- `TestEarlyDisabledGate`: el gate de la CLI se dispara ANTES de
  construir absolutamente nada (ni `SQLiteMarketDataRepository`, ni
  `RepositoryMarketPriceProvider`, ni `build_paper_trading_context()`,
  ni `SystemClock`/`UUIDIdGenerator`) -- la evidencia real de que no hay
  inicialización ni escritura SQLite con `enabled=false`.
"""

import argparse
import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.paper_trading import order_cli
from src.paper_trading.application import PaperTradingDisabledError
from src.paper_trading.composition import build_paper_trading_context
from src.paper_trading.enums import OrderSide, OrderStatus, PositionSide
from src.paper_trading.models import CashBalance
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.utils.config import PaperTradingConfig


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    def __init__(self):
        self._counters = {"order": 0, "exec": 0, "trade": 0, "audit": 0}
        self.total_calls = 0

    def _next(self, prefix: str) -> str:
        self._counters[prefix] += 1
        self.total_calls += 1
        return f"{prefix}-{self._counters[prefix]}"

    def new_order_id(self) -> str:
        return self._next("order")

    def new_execution_id(self) -> str:
        return self._next("exec")

    def new_trade_id(self) -> str:
        return self._next("trade")

    def new_reconciliation_audit_id(self) -> str:
        return self._next("audit")


class FakePriceProvider:
    """Precios en memoria, nunca Binance/requests (mismo patrón que
    test_paper_trading_application.py)."""

    def __init__(self, prices: dict):
        self._prices = dict(prices)
        self.queried_symbols: list = []

    def get_current_price(self, exchange, symbol):
        key = (exchange, symbol)
        self.queried_symbols.append(key)
        if key not in self._prices:
            raise ValueError(f"No hay precio para {key}.")
        return self._prices[key]

    def get_current_prices(self, symbols):
        return {key: self.get_current_price(*key) for key in symbols}


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _config(tmp_path, **overrides) -> PaperTradingConfig:
    defaults = dict(
        enabled=True, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"), rules_version="v1",
    )
    defaults.update(overrides)
    return PaperTradingConfig(**defaults)


def _context(tmp_path, prices=None, id_generator=None, **config_overrides):
    default_prices = {("Binance", "BTCUSDT"): Decimal("50000")}
    return build_paper_trading_context(
        config=_config(tmp_path, **config_overrides),
        clock=FixedClock(_now()),
        id_generator=id_generator or DeterministicIdGenerator(),
        market_price_provider=FakePriceProvider(default_prices if prices is None else prices),
    )


def _fake_settings(enabled: bool = True):
    """El único campo de `Settings` que `main()` lee directamente antes
    de construir el contexto es `settings.paper_trading.enabled` (Etapa
    6.19.1) -- `_build_context` se monkeypatchea aparte para devolver un
    `PaperTradingContext` ya armado, así que un `SimpleNamespace` mínimo
    alcanza para las pruebas de `_load_settings`."""
    return SimpleNamespace(paper_trading=SimpleNamespace(enabled=enabled))


def _patch_context(monkeypatch, context, *, settings_enabled: bool = True):
    """Inyecta un `PaperTradingContext` de prueba ya construido.
    `settings_enabled` controla lo que `_load_settings()` reporta (el
    gate temprano de la CLI, Etapa 6.19.1) -- independiente de
    `context.application._config.enabled` (lo que ya trae el contexto
    inyectado, usado por `TestApplicationDefenseInDepthWhenDisabled`
    para probar la defensa de `PaperTradingApplication` por separado)."""
    monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(settings_enabled))
    monkeypatch.setattr(order_cli, "_build_context", lambda settings: context)


# ==========================================================================
# §27 -- Pruebas unitarias de parser/validación
# ==========================================================================

class TestBuildParser:
    def test_build_parser_returns_argument_parser(self):
        import argparse
        parser = order_cli.build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_main_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main(["--help"])
        assert excinfo.value.code == 0
        assert "--confirm" in capsys.readouterr().out

    def test_accept_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main(["accept", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--exchange" in out and "--symbol" in out and "--side" in out and "--quantity" in out

    def test_fill_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main(["fill", "--help"])
        assert excinfo.value.code == 0
        assert "--order-id" in capsys.readouterr().out

    def test_cancel_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main(["cancel", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--order-id" in out and "--reason" in out

    def test_submit_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main(["submit", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--exchange" in out and "--symbol" in out and "--side" in out and "--quantity" in out

    def test_missing_subcommand_exits_2(self):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main([])
        assert excinfo.value.code == 2

    def test_confirm_help_text_explains_semantics(self, capsys):
        with pytest.raises(SystemExit):
            order_cli.main(["--help"])
        out = capsys.readouterr().out
        assert "simulated" in out.lower() or "simulada" in out.lower()


class TestQuantityValidation:
    def test_valid_quantity_parses_as_decimal(self):
        assert order_cli._quantity_type("0.01") == Decimal("0.01")

    def test_rejects_empty(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("")

    def test_rejects_zero(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("0")

    def test_rejects_negative(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("-1")

    def test_rejects_nan(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("NaN")

    def test_rejects_infinity(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("Infinity")

    def test_rejects_negative_infinity(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("-Infinity")

    def test_rejects_invalid_text(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._quantity_type("abc")

    def test_never_rounds(self):
        assert order_cli._quantity_type("0.123456789") == Decimal("0.123456789")

    def test_invalid_quantity_via_main_exits_2(self):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main([
                "accept", "--exchange", "Binance", "--symbol", "BTCUSDT",
                "--side", "BUY", "--quantity", "0", "--confirm",
            ])
        assert excinfo.value.code == 2


class TestSideValidation:
    def test_valid_buy(self):
        assert order_cli._side_type("BUY") == OrderSide.BUY

    def test_valid_sell(self):
        assert order_cli._side_type("SELL") == OrderSide.SELL

    def test_invalid_side_rejected(self):
        with pytest.raises(argparse.ArgumentTypeError):
            order_cli._side_type("LONG")

    def test_invalid_side_via_main_exits_2(self):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main([
                "accept", "--exchange", "Binance", "--symbol", "BTCUSDT",
                "--side", "SHORT", "--quantity", "0.1", "--confirm",
            ])
        assert excinfo.value.code == 2


class TestNonEmptyTextTypeValidation:
    def test_valid_text_passes_through(self):
        validator = order_cli._non_empty_text_type("--reason")
        assert validator("Cancelación manual") == "Cancelación manual"

    def test_rejects_empty(self):
        validator = order_cli._non_empty_text_type("--reason")
        with pytest.raises(argparse.ArgumentTypeError):
            validator("")

    def test_invalid_reason_via_main_exits_2(self):
        with pytest.raises(SystemExit) as excinfo:
            order_cli.main(["cancel", "--order-id", "order-1", "--reason", "", "--confirm"])
        assert excinfo.value.code == 2


# ==========================================================================
# §15/§31 -- Confirmación obligatoria
# ==========================================================================

class TestConfirmationRequired:
    _COMMANDS = {
        "accept": ["accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1"],
        "fill": ["fill", "--order-id", "order-1"],
        "cancel": ["cancel", "--order-id", "order-1", "--reason", "test"],
        "submit": ["submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1"],
    }

    @pytest.mark.parametrize("argv", _COMMANDS.values(), ids=_COMMANDS.keys())
    def test_without_confirm_exits_5(self, argv, capsys):
        exit_code = order_cli.main(list(argv))
        assert exit_code == 5
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "confirm" in captured.err.lower()

    @pytest.mark.parametrize("argv", _COMMANDS.values(), ids=_COMMANDS.keys())
    def test_without_confirm_never_builds_context(self, argv, monkeypatch):
        def _fail():
            raise AssertionError("_build_context() must not be called without --confirm")
        monkeypatch.setattr(order_cli, "_build_context", _fail)
        order_cli.main(list(argv))

    @pytest.mark.parametrize("argv", _COMMANDS.values(), ids=_COMMANDS.keys())
    def test_without_confirm_never_calls_load_settings(self, argv, monkeypatch):
        def _fail():
            raise AssertionError("load_settings() must not be called without --confirm")
        monkeypatch.setattr(order_cli, "load_settings", _fail)
        order_cli.main(list(argv))

    def test_confirm_before_subcommand_also_works(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "--confirm", "accept", "--exchange", "Binance", "--symbol", "BTCUSDT",
            "--side", "BUY", "--quantity", "0.1",
        ])
        assert exit_code == 0


# ==========================================================================
# §17 -- --format antes/después del subcomando
# ==========================================================================

class TestFormatPosition:
    def test_format_json_after_subcommand(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is True

    def test_format_json_before_subcommand(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "--format", "json", "--confirm", "accept", "--exchange", "Binance",
            "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is True

    def test_default_format_is_table(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        out = capsys.readouterr().out
        assert "approved: true" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

    def test_duplicated_format_last_value_wins(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "--format", "table", "accept", "--exchange", "Binance", "--symbol", "BTCUSDT",
            "--side", "BUY", "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is True


# ==========================================================================
# §9-§12 -- Comportamiento por subcomando (integración real, tmp_path)
# ==========================================================================

class TestAcceptCommand:
    def test_accept_buy_success_shows_required_fields(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is True
        assert payload["status"] == "PENDING"
        assert payload["order_id"] == "order-1"
        assert Decimal(payload["reserved_price"]) == Decimal("50000")
        assert payload["quantity"] == "0.1"

    def test_accept_persists_pending_order_with_reservation(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order = context.repository.get_order("order-1")
        assert order.status == OrderStatus.PENDING
        assert order.reserved_price == Decimal("50000")
        balance = context.repository.get_cash_balance("USDT")
        assert balance.reserved_balance > Decimal("0")

    def test_accept_rejected_by_risk_exits_6_and_no_partial_state(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, max_order_value=Decimal("1"))
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is False
        assert payload["risk_code"] == "MAX_ORDER_VALUE_EXCEEDED"
        assert "reserved_price" not in payload
        assert context.repository.get_order(payload["order_id"]) is None
        assert context.repository.get_cash_balance("USDT").reserved_balance == Decimal("0")


class TestFillCommand:
    def test_fill_pending_order_success(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        capsys.readouterr()
        exit_code = order_cli.main(["fill", "--order-id", "order-1", "--confirm", "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "FILLED"
        assert payload["execution_id"] == "exec-1"
        assert Decimal(payload["execution_price"]) == Decimal("50000")
        assert payload["trade_id"] is None

    def test_fill_updates_position_and_balance(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["fill", "--order-id", "order-1", "--confirm"])
        position = context.repository.get_position("Binance", "BTCUSDT")
        assert position.side == PositionSide.LONG
        assert position.quantity == Decimal("0.1")
        balance = context.repository.get_cash_balance("USDT")
        assert balance.reserved_balance == Decimal("0")

    def test_fill_nonexistent_order_exits_7(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main(["fill", "--order-id", "does-not-exist", "--confirm"])
        assert exit_code == 7
        assert capsys.readouterr().err.strip() != ""

    def test_fill_new_order_not_pending_exits_7(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["fill", "--order-id", "order-1", "--confirm"])
        exit_code = order_cli.main(["fill", "--order-id", "order-1", "--confirm"])
        assert exit_code == 7


class TestCancelCommand:
    def test_cancel_pending_order_success(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        capsys.readouterr()
        exit_code = order_cli.main([
            "cancel", "--order-id", "order-1", "--reason", "Cancelación manual del operador",
            "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "CANCELLED"
        assert payload["cancellation_reason"] == "Cancelación manual del operador"
        assert payload["reservation_released"] is True

    def test_cancel_releases_reservation_completely(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["cancel", "--order-id", "order-1", "--reason", "test", "--confirm"])
        balance = context.repository.get_cash_balance("USDT")
        assert balance.reserved_balance == Decimal("0")
        assert balance.total_balance == Decimal("10000")

    def test_cancel_nonexistent_order_exits_7(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main(["cancel", "--order-id", "missing", "--reason", "test", "--confirm"])
        assert exit_code == 7

    def test_cancel_already_filled_order_exits_7(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["fill", "--order-id", "order-1", "--confirm"])
        exit_code = order_cli.main(["cancel", "--order-id", "order-1", "--reason", "test", "--confirm"])
        assert exit_code == 7


class TestSubmitCommand:
    def test_submit_buy_full_flow(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is True
        assert payload["status"] == "FILLED"
        assert payload["execution_id"] == "exec-1"
        assert payload["trade_id"] is None

    def test_submit_persists_full_result(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order = context.repository.get_order("order-1")
        assert order.status == OrderStatus.FILLED
        position = context.repository.get_position("Binance", "BTCUSDT")
        assert position.quantity == Decimal("0.1")

    def test_submit_rejected_by_risk_exits_6_no_partial_state(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, max_order_value=Decimal("1"))
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["approved"] is False
        assert "execution_id" not in payload
        assert context.repository.get_order(payload["order_id"]) is None

    def test_submit_sell_creates_trade(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, prices={("Binance", "BTCUSDT"): Decimal("50000")})
        _patch_context(monkeypatch, context)
        order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        capsys.readouterr()
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "SELL",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["trade_id"] is not None
        assert context.repository.get_position("Binance", "BTCUSDT").side == PositionSide.FLAT


# ==========================================================================
# §29 -- Rechazo por riesgo (casos adicionales)
# ==========================================================================

class TestRiskRejection:
    def test_buy_without_enough_cash_exits_6(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, initial_capital=Decimal("1"))
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "1", "--confirm", "--format", "json",
        ])
        assert exit_code == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["risk_code"] == "INSUFFICIENT_AVAILABLE_CASH"

    def test_max_position_value_exceeded_exits_6(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, max_position_value=Decimal("100"))
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["risk_code"] == "MAX_POSITION_VALUE_EXCEEDED"

    def test_sell_without_position_exits_6(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "SELL",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["risk_code"] == "SELL_WITHOUT_POSITION"

    def test_sell_more_than_available_quantity_exits_6(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        capsys.readouterr()
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "SELL",
            "--quantity", "5", "--confirm", "--format", "json",
        ])
        assert exit_code == 6
        payload = json.loads(capsys.readouterr().out)
        assert payload["risk_code"] == "INSUFFICIENT_AVAILABLE_QUANTITY"


# ==========================================================================
# §16/§30 (Etapa 6.19) -- Application ya construida + deshabilitada
# (defensa de dominio, PaperTradingApplication._require_enabled(), sin
# relación con el gate temprano de la CLI -- ver TestEarlyDisabledGate
# más abajo para la evidencia real de "sin inicialización" de la 6.19.1)
# ==========================================================================

_DISABLED_COMMANDS = {
    "accept": ["accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1"],
    "fill": ["fill", "--order-id", "order-1"],
    "cancel": ["cancel", "--order-id", "order-1", "--reason", "test"],
    "submit": ["submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1"],
}


class TestApplicationDefenseInDepthWhenDisabled:
    """El `PaperTradingContext` inyectado ya está completamente
    construido, con `enabled=False` en su propia config -- deliberado:
    demuestra que `PaperTradingApplication._require_enabled()` (Etapa
    6.5, sin modificar) sigue rechazando por su cuenta incluso si algo
    llegara a construir el contexto (`_load_settings()` se monkeypatchea
    aquí para reportar `enabled=True`, ver `_patch_context`, así que
    esta prueba nunca ejercita el gate temprano de la CLI -- esa
    evidencia vive en `TestEarlyDisabledGate`)."""

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_disabled_exits_4_with_sanitized_message(self, argv, tmp_path, monkeypatch, capsys):
        id_generator = DeterministicIdGenerator()
        context = _context(tmp_path, id_generator=id_generator, enabled=False)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([*argv, "--confirm"])
        assert exit_code == 4
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Paper Trading is disabled in configuration."

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_disabled_never_queries_price_or_generates_ids(self, argv, tmp_path, monkeypatch):
        id_generator = DeterministicIdGenerator()
        context = _context(
            tmp_path, id_generator=id_generator, enabled=False,
            prices={("Binance", "BTCUSDT"): Decimal("50000")},
        )
        price_provider = context.application._price_provider
        _patch_context(monkeypatch, context)
        order_cli.main([*argv, "--confirm"])
        assert price_provider.queried_symbols == []
        assert id_generator.total_calls == 0

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_disabled_never_writes(self, argv, tmp_path, monkeypatch):
        context = _context(tmp_path, enabled=False)
        before = context.repository.get_cash_balance("USDT")
        _patch_context(monkeypatch, context)
        order_cli.main([*argv, "--confirm"])
        after = context.repository.get_cash_balance("USDT")
        assert before == after
        assert context.repository.fetch_orders() == []


# ==========================================================================
# Etapa 6.19.1 -- Gate temprano de habilitación: el defecto bloqueante
# detectado en la auditoría era que `_build_context()` (y, por lo tanto,
# `SQLiteMarketDataRepository`/su `init()`/`RepositoryMarketPriceProvider`/
# `build_paper_trading_context()`/`SystemClock`/`UUIDIdGenerator`) se
# ejecutaba ANTES de que `PaperTradingApplication._require_enabled()`
# tuviera oportunidad de rechazar -- con `enabled=false`, la CLI podía
# crear bases/tablas/balance antes de devolver el código 4. Estas
# pruebas demuestran que ninguno de esos colaboradores llega a
# construirse: `_load_settings()` se monkeypatchea para reportar
# `enabled=False`, y `_build_context`/las clases productivas se
# reemplazan por espías que fallan si se instancian.
# ==========================================================================

class TestEarlyDisabledGate:
    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_exits_4_before_building_any_context(self, argv, monkeypatch, capsys):
        monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(enabled=False))

        def _fail(settings):
            raise AssertionError("_build_context(settings) must not be called when disabled")

        monkeypatch.setattr(order_cli, "_build_context", _fail)

        exit_code = order_cli.main([*argv, "--confirm"])
        assert exit_code == 4
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Paper Trading is disabled in configuration."

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_never_instantiates_market_repository(self, argv, monkeypatch):
        monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(enabled=False))

        class _SpyMarketRepository:
            def __init__(self, *args, **kwargs):
                raise AssertionError("SQLiteMarketDataRepository must not be instantiated when disabled")

        monkeypatch.setattr(order_cli, "SQLiteMarketDataRepository", _SpyMarketRepository)
        assert order_cli.main([*argv, "--confirm"]) == 4

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_never_builds_paper_trading_context(self, argv, monkeypatch):
        monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(enabled=False))

        def _fail(**kwargs):
            raise AssertionError("build_paper_trading_context() must not be called when disabled")

        monkeypatch.setattr(order_cli, "build_paper_trading_context", _fail)
        assert order_cli.main([*argv, "--confirm"]) == 4

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_never_constructs_price_provider(self, argv, monkeypatch):
        monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(enabled=False))

        class _SpyPriceProvider:
            def __init__(self, *args, **kwargs):
                raise AssertionError("RepositoryMarketPriceProvider must not be instantiated when disabled")

        monkeypatch.setattr(order_cli, "RepositoryMarketPriceProvider", _SpyPriceProvider)
        assert order_cli.main([*argv, "--confirm"]) == 4

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_never_constructs_clock_or_id_generator(self, argv, monkeypatch):
        monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(enabled=False))

        class _SpyClock:
            def __init__(self, *args, **kwargs):
                raise AssertionError("SystemClock must not be instantiated when disabled")

        class _SpyIdGenerator:
            def __init__(self, *args, **kwargs):
                raise AssertionError("UUIDIdGenerator must not be instantiated when disabled")

        monkeypatch.setattr(order_cli, "SystemClock", _SpyClock)
        monkeypatch.setattr(order_cli, "UUIDIdGenerator", _SpyIdGenerator)
        assert order_cli.main([*argv, "--confirm"]) == 4

    def test_fill_of_nonexistent_order_still_exits_4_not_7(self, monkeypatch, capsys):
        """§9 del ticket: el resultado no debe depender de la existencia
        del order_id -- con enabled=false, incluso un --order-id que no
        existiría en ninguna base también termina en 4, nunca en 7."""
        monkeypatch.setattr(order_cli, "_load_settings", lambda: _fake_settings(enabled=False))

        def _fail(settings):
            raise AssertionError("_build_context(settings) must not be called when disabled")

        monkeypatch.setattr(order_cli, "_build_context", _fail)

        exit_code = order_cli.main(["fill", "--order-id", "does-not-exist-anywhere", "--confirm"])
        assert exit_code == 4
        assert capsys.readouterr().err.strip() == "Paper Trading is disabled in configuration."


class TestNoMarketDatabaseInitializationWhenDisabled:
    """§10 del ticket: con `enabled=false`, ni el archivo de la base de
    mercado ni su directorio deben crearse -- prueba de integración
    real, sin reemplazar `_build_context` (solo `_load_settings`)."""

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_market_database_file_is_never_created(self, argv, tmp_path, monkeypatch):
        market_db_dir = tmp_path / "does_not_exist_yet"
        market_db_path = market_db_dir / "market.db"
        pt_db_path = tmp_path / "does_not_exist_yet_either" / "paper_trading.db"

        settings = SimpleNamespace(
            database=SimpleNamespace(sqlite_path=str(market_db_path)),
            paper_trading=_config(tmp_path, database_path=str(pt_db_path), enabled=False),
        )
        monkeypatch.setattr(order_cli, "_load_settings", lambda: settings)

        exit_code = order_cli.main([*argv, "--confirm"])

        assert exit_code == 4
        assert not market_db_dir.exists()
        assert not market_db_path.exists()


class TestNoPaperTradingInitializationWhenDisabled:
    """§11 del ticket: con `enabled=false`, `build_paper_trading_context()`
    nunca se invoca -- ni la base de Paper Trading ni su directorio se
    crean, ni se siembra ningún `CashBalance`."""

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_paper_trading_database_file_is_never_created(self, argv, tmp_path, monkeypatch):
        market_db_path = tmp_path / "market_dir" / "market.db"
        pt_db_dir = tmp_path / "pt_dir"
        pt_db_path = pt_db_dir / "paper_trading.db"

        settings = SimpleNamespace(
            database=SimpleNamespace(sqlite_path=str(market_db_path)),
            paper_trading=_config(tmp_path, database_path=str(pt_db_path), enabled=False),
        )
        monkeypatch.setattr(order_cli, "_load_settings", lambda: settings)

        def _fail(**kwargs):
            raise AssertionError("build_paper_trading_context() must not be called when disabled")

        monkeypatch.setattr(order_cli, "build_paper_trading_context", _fail)

        exit_code = order_cli.main([*argv, "--confirm"])

        assert exit_code == 4
        assert not pt_db_dir.exists()
        assert not pt_db_path.exists()


class TestDisabledWithNonExistentDatabases:
    """§14 del ticket -- la prueba principal que faltó en la Etapa 6.19:
    dos rutas SQLite inexistentes, solo `_load_settings()` reemplazado
    (nunca `_build_context`, para ejercitar el código productivo real de
    principio a fin), los cuatro comandos confirmados. Ningún archivo ni
    directorio SQLite nuevo debe aparecer."""

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_no_sqlite_artifact_is_created_end_to_end(self, argv, tmp_path, monkeypatch, capsys):
        market_db_path = tmp_path / "market_subdir" / "market.db"
        pt_db_path = tmp_path / "pt_subdir" / "paper_trading.db"
        assert not market_db_path.exists()
        assert not pt_db_path.exists()

        settings = SimpleNamespace(
            database=SimpleNamespace(sqlite_path=str(market_db_path)),
            paper_trading=_config(tmp_path, database_path=str(pt_db_path), enabled=False),
        )
        monkeypatch.setattr(order_cli, "_load_settings", lambda: settings)

        exit_code = order_cli.main([*argv, "--confirm"])

        assert exit_code == 4
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == "Paper Trading is disabled in configuration."
        assert not market_db_path.exists()
        assert not market_db_path.parent.exists()
        assert not pt_db_path.exists()
        assert not pt_db_path.parent.exists()


class TestDisabledWithExistingDatabases:
    """§15 del ticket: bases ya existentes con contenido identificable --
    con `enabled=false`, ni el schema ni las filas deben cambiar en
    absoluto para ninguno de los cuatro comandos."""

    def _seed_databases(self, tmp_path):
        market_db_path = tmp_path / "market.db"
        pt_db_path = tmp_path / "pt.db"

        from src.database.sqlite_repository import SQLiteMarketDataRepository as RealMarketRepo
        market_repo = RealMarketRepo(str(market_db_path))
        market_repo.init()

        pt_repo = SQLitePaperTradingRepository(str(pt_db_path))
        pt_repo.init()
        pt_repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        return market_db_path, pt_db_path, pt_repo

    @staticmethod
    def _snapshot(db_path):
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            tables = sorted(
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            )
            contents = {
                table: conn.execute(f"SELECT * FROM {table}").fetchall()
                for table in tables
            }
        finally:
            conn.close()
        return tables, contents

    @pytest.mark.parametrize("argv", _DISABLED_COMMANDS.values(), ids=_DISABLED_COMMANDS.keys())
    def test_existing_databases_are_untouched(self, argv, tmp_path, monkeypatch):
        market_db_path, pt_db_path, _ = self._seed_databases(tmp_path)

        settings = SimpleNamespace(
            database=SimpleNamespace(sqlite_path=str(market_db_path)),
            paper_trading=_config(tmp_path, database_path=str(pt_db_path), enabled=False),
        )
        monkeypatch.setattr(order_cli, "_load_settings", lambda: settings)

        market_before = self._snapshot(market_db_path)
        pt_before = self._snapshot(pt_db_path)

        exit_code = order_cli.main([*argv, "--confirm"])

        assert exit_code == 4
        assert self._snapshot(market_db_path) == market_before
        assert self._snapshot(pt_db_path) == pt_before


# ==========================================================================
# §17/§18 -- Carga única de configuración, con enabled=true
# ==========================================================================

class TestSettingsLoadedExactlyOnce:
    def test_enabled_path_calls_load_settings_and_build_context_once(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        load_settings_calls = []
        build_context_calls = []

        def _spy_load_settings():
            load_settings_calls.append(1)
            return _fake_settings(enabled=True)

        def _spy_build_context(settings):
            build_context_calls.append(settings)
            return context

        monkeypatch.setattr(order_cli, "_load_settings", _spy_load_settings)
        monkeypatch.setattr(order_cli, "_build_context", _spy_build_context)

        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])

        assert exit_code == 0
        assert len(load_settings_calls) == 1
        assert len(build_context_calls) == 1

    def test_disabled_path_calls_load_settings_exactly_once_and_never_builds(self, monkeypatch):
        load_settings_calls = []

        def _spy_load_settings():
            load_settings_calls.append(1)
            return _fake_settings(enabled=False)

        def _fail(settings):
            raise AssertionError("_build_context(settings) must not be called when disabled")

        monkeypatch.setattr(order_cli, "_load_settings", _spy_load_settings)
        monkeypatch.setattr(order_cli, "_build_context", _fail)

        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])

        assert exit_code == 4
        assert len(load_settings_calls) == 1

    def test_without_confirm_never_calls_load_settings_at_all(self, monkeypatch):
        def _fail():
            raise AssertionError("_load_settings() must not be called without --confirm")

        monkeypatch.setattr(order_cli, "_load_settings", _fail)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1",
        ])
        assert exit_code == 5


# ==========================================================================
# §17 -- Con enabled=true, los cuatro comandos siguen funcionando
# ==========================================================================

class TestEnabledStillWorks:
    def test_accept_still_works(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        assert json.loads(capsys.readouterr().out)["approved"] is True

    def test_submit_still_works(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        assert exit_code == 0
        assert json.loads(capsys.readouterr().out)["status"] == "FILLED"

    def test_fill_still_works(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        capsys.readouterr()
        exit_code = order_cli.main(["fill", "--order-id", "order-1", "--confirm", "--format", "json"])
        assert exit_code == 0
        assert json.loads(capsys.readouterr().out)["status"] == "FILLED"


# ==========================================================================
# §22 -- Manejo de excepciones no relacionadas con riesgo/estado
# ==========================================================================

class TestUnexpectedErrorHandling:
    def test_missing_market_price_maps_to_operational_error_exit_8(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, prices={})
        _patch_context(monkeypatch, context)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        assert exit_code == 8
        assert capsys.readouterr().err.strip() != ""

    def test_unexpected_exception_is_sanitized_and_exits_9(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)

        def _boom(*args, **kwargs):
            raise RuntimeError("boom with a secret token=abc123")

        monkeypatch.setattr(context.application, "accept_manual_market_order", _boom)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        assert exit_code == 9
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "token=abc123" not in captured.err
        assert captured.err.strip() == "Order operation failed unexpectedly."

    def test_configuration_error_exits_3(self, monkeypatch, capsys):
        def _fail():
            raise FileNotFoundError("config/config.yaml not found")

        monkeypatch.setattr(order_cli, "load_settings", _fail)
        exit_code = order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        assert exit_code == 3
        assert capsys.readouterr().err.strip() != ""


# ==========================================================================
# §24 -- Atomicidad (sin estados parciales)
# ==========================================================================

class TestAtomicity:
    def test_rejected_accept_leaves_no_trace(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, max_order_value=Decimal("1"))
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm", "--format", "json",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert context.repository.get_order(payload["order_id"]) is None
        assert context.repository.fetch_positions() == []

    def test_invalid_fill_leaves_no_partial_change(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        before = context.repository.get_order("order-1")
        exit_code = order_cli.main(["fill", "--order-id", "missing-order", "--confirm"])
        assert exit_code == 7
        after = context.repository.get_order("order-1")
        assert before == after
        assert context.repository.fetch_executions() == []

    def test_invalid_cancel_leaves_no_partial_change(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["fill", "--order-id", "order-1", "--confirm"])
        balance_before = context.repository.get_cash_balance("USDT")
        exit_code = order_cli.main(["cancel", "--order-id", "order-1", "--reason", "test", "--confirm"])
        assert exit_code == 7
        assert context.repository.get_cash_balance("USDT") == balance_before


# ==========================================================================
# §25 -- Idempotencia y repetición
# ==========================================================================

class TestIdempotency:
    def test_double_fill_is_rejected_without_duplicating_execution(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        assert order_cli.main(["fill", "--order-id", "order-1", "--confirm"]) == 0
        assert order_cli.main(["fill", "--order-id", "order-1", "--confirm"]) == 7
        assert len(context.repository.fetch_executions()) == 1

    def test_double_cancel_is_rejected(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        assert order_cli.main(["cancel", "--order-id", "order-1", "--reason", "a", "--confirm"]) == 0
        assert order_cli.main(["cancel", "--order-id", "order-1", "--reason", "b", "--confirm"]) == 7

    def test_fill_after_cancel_is_rejected(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["cancel", "--order-id", "order-1", "--reason", "a", "--confirm"])
        assert order_cli.main(["fill", "--order-id", "order-1", "--confirm"]) == 7

    def test_cancel_after_fill_is_rejected(self, tmp_path, monkeypatch):
        context = _context(tmp_path)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        order_cli.main(["fill", "--order-id", "order-1", "--confirm"])
        assert order_cli.main(["cancel", "--order-id", "order-1", "--reason", "a", "--confirm"]) == 7


# ==========================================================================
# §32 -- Subprocess (solo --help y errores previos a construir contexto)
# ==========================================================================

class TestSubprocess:
    def test_help_via_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.order_cli", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert "--confirm" in result.stdout

    def test_submit_without_confirm_via_subprocess_never_touches_real_config(self):
        """No usa --database-path (no existe): la ausencia de --confirm
        garantiza que _build_context()/load_settings() nunca se llaman,
        así que este subprocess es seguro incluso contra la config/base
        reales del repositorio (ver §32 del ticket)."""
        result = subprocess.run(
            [
                sys.executable, "-m", "src.paper_trading.order_cli", "submit",
                "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.01",
            ],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 5
        assert result.stdout == ""
        assert "confirm" in result.stderr.lower()


# ==========================================================================
# §33 -- No escritura sin confirmación (prueba integral con snapshot)
# ==========================================================================

class TestNoWriteWithoutConfirmation:
    def test_no_subcommand_writes_anything_without_confirm(self, tmp_path):
        repo = SQLitePaperTradingRepository(str(tmp_path / "snap.db"))
        repo.init()
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))

        def _snapshot():
            return (
                repo.get_cash_balance("USDT"),
                repo.fetch_orders(),
                repo.fetch_positions(),
                repo.fetch_executions(),
            )

        before = _snapshot()
        for argv in [
            ["accept", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1"],
            ["fill", "--order-id", "whatever"],
            ["cancel", "--order-id", "whatever", "--reason", "test"],
            ["submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY", "--quantity", "0.1"],
        ]:
            exit_code = order_cli.main(argv)
            assert exit_code == 5
        after = _snapshot()
        assert before == after


# ==========================================================================
# §34 -- Aislamiento estructural (AST, no búsqueda textual)
# ==========================================================================

class TestStructuralIsolation:
    _FORBIDDEN_NAMES = {
        "RiskEngine", "FillEngine", "PositionEngine", "PnLEngine", "ReservationEngine",
        "SQLitePaperTradingRepository",
    }

    @staticmethod
    def _tree():
        source = open(order_cli.__file__, encoding="utf-8").read()
        return ast.parse(source)

    def test_does_not_import_forbidden_engine_or_repository_names(self):
        imported_names = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)
        overlap = imported_names & self._FORBIDDEN_NAMES
        assert not overlap, f"forbidden names imported: {overlap}"

    def test_does_not_import_sqlite3(self):
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Import):
                assert not any(alias.name == "sqlite3" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "sqlite3"

    def test_imports_application_and_composition_as_expected(self):
        modules = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[-1])
        assert "application" in modules
        assert "composition" in modules


# ==========================================================================
# §35/§44 -- Seguridad
# ==========================================================================

class TestSecurity:
    def test_no_forbidden_write_calls_or_sql_in_source(self):
        source = open(order_cli.__file__, encoding="utf-8").read()
        forbidden_substrings = ["INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "ALTER TABLE", "DROP TABLE"]
        for token in forbidden_substrings:
            assert token not in source

    def test_disabled_message_has_no_traceback_markers(self, tmp_path, monkeypatch, capsys):
        context = _context(tmp_path, enabled=False)
        _patch_context(monkeypatch, context)
        order_cli.main([
            "submit", "--exchange", "Binance", "--symbol", "BTCUSDT", "--side", "BUY",
            "--quantity", "0.1", "--confirm",
        ])
        err = capsys.readouterr().err
        assert "Traceback" not in err
        assert "File \"" not in err
