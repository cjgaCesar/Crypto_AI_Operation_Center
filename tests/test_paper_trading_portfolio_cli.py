"""
Pruebas para src/paper_trading/portfolio_cli.py (Etapa 6.18): CLI
operativa y estrictamente de solo lectura para consultar el estado de
Paper Trading.

Nunca construye un `PaperTradingApplication`/`PaperTradingService`/
Composition Root completo -- usa `SQLitePaperTradingRepository`
directamente (el mismo repositorio productivo, en modo lectura-
escritura normal) SOLO para sembrar datos de prueba; la CLI bajo
prueba siempre abre su propia conexión `mode=ro` independiente.
"""

import argparse
import ast
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.paper_trading import portfolio_cli
from src.paper_trading.alert_models import (
    AlertStatus, AlertType, InspectionAlert, InspectionAlertChannelDelivery,
)
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.models import CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade
from src.paper_trading.reconciliation_models import IssueSeverity, ReconciliationAuditRecord
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    return repo


def _run(db_path: str, args: list, format_: str = "table"):
    return portfolio_cli.main(["--database-path", db_path, "--format", format_, *args])


class TestHelp:
    """§7/§36: la ayuda principal y de cada subcomando debe funcionar sin
    tocar ninguna base de datos ni configuración."""

    def test_main_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--help"])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        for command in (
            "summary", "balances", "positions", "orders", "executions", "trades",
            "snapshots", "inspections", "alerts", "deliveries", "reconciliation-audits",
        ):
            assert command in output

    @pytest.mark.parametrize("command", ["summary", "orders", "alerts", "deliveries"])
    def test_subcommand_help_exits_zero(self, command, capsys):
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main([command, "--help"])
        assert exc_info.value.code == 0

    def test_real_module_invocation_help(self):
        """§36: invocación real del módulo (no solo main() en proceso)."""
        result = subprocess.run(
            [sys.executable, "-m", "src.paper_trading.portfolio_cli", "--help"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert "summary" in result.stdout

    def test_main_help_mentions_currency(self, capsys):
        """Etapa 6.21, §25: --currency debe aparecer en la ayuda principal."""
        with pytest.raises(SystemExit):
            portfolio_cli.main(["--help"])
        assert "--currency" in capsys.readouterr().out

    def test_summary_help_mentions_currency(self, capsys):
        with pytest.raises(SystemExit):
            portfolio_cli.main(["summary", "--help"])
        assert "--currency" in capsys.readouterr().out


class TestEntryPoint:
    def test_main_returns_int_never_calls_sys_exit_internally(self, tmp_path):
        """§6: main() debe devolver un código de salida (para --help/
        errores de argparse, argparse mismo lanza SystemExit -- eso es
        aceptable y coherente con el código 2 esperado; para el resto de
        la lógica, main() siempre retorna en vez de salir)."""
        db_path = str(tmp_path / "nonexistent.db")
        result = portfolio_cli.main(["--database-path", db_path, "summary"])
        assert isinstance(result, int)


class TestExitCodes:
    """§24: 0 éxito, 2 error de argumentos, 3 configuración inválida, 4
    base inexistente/inaccesible, 5 error de consulta controlado."""

    def test_exit_0_on_success(self, tmp_path):
        repo = _repo(tmp_path)
        assert _run(repo.db_path, ["summary"]) == portfolio_cli.EXIT_OK == 0

    def test_exit_2_on_argparse_error(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "orders", "--status", "BOGUS"])
        assert exc_info.value.code == 2

    def test_exit_2_on_missing_required_snapshot_type(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "snapshots"])
        assert exc_info.value.code == 2

    def test_exit_3_on_invalid_configuration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.utils.config.load_settings",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no config")),
        )
        exit_code = portfolio_cli.main(["summary"])  # sin --database-path: fuerza load_settings()
        assert exit_code == portfolio_cli.EXIT_CONFIG_ERROR == 3

    def test_exit_4_on_missing_database(self, tmp_path):
        db_path = str(tmp_path / "missing.db")
        assert _run(db_path, ["summary"]) == portfolio_cli.EXIT_DATABASE_ERROR == 4

    def test_exit_4_on_directory_as_database_path(self, tmp_path):
        directory = tmp_path / "a_directory"
        directory.mkdir()
        assert _run(str(directory), ["summary"]) == 4

    def test_exit_4_on_file_without_paper_trading_schema(self, tmp_path):
        db_path = tmp_path / "not_paper_trading.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        assert _run(str(db_path), ["summary"]) == 4

    def test_exit_5_on_unexpected_sqlite_error(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)

        def _raise(*args, **kwargs):
            raise sqlite3.OperationalError("simulated failure")

        monkeypatch.setattr(portfolio_cli, "_fetch_summary", _raise)
        exit_code = _run(repo.db_path, ["summary"])
        assert exit_code == portfolio_cli.EXIT_QUERY_ERROR == 5


class TestDatabaseNotFoundGuarantees:
    """§25: la base inexistente nunca se crea, ni el directorio, ni
    ninguna tabla; stdout queda vacío; stderr explica el motivo."""

    def test_missing_database_creates_nothing(self, tmp_path, capsys):
        db_path = tmp_path / "missing.db"
        exit_code = _run(str(db_path), ["summary"])
        assert exit_code == 4
        assert not db_path.exists()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err != ""
        assert "does not exist" in captured.err.lower()


class TestDatabaseWithoutData:
    """§26: base inicializada (schema real) pero sin datos todavía ->
    código 0, resultados vacíos -- nunca se inicializa el schema
    automáticamente."""

    def test_initialized_empty_database_returns_zero_with_empty_results(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        exit_code = _run(repo.db_path, ["orders"])
        assert exit_code == 0
        assert "No records found." in capsys.readouterr().out

    def test_summary_on_empty_database_shows_none_and_zero_counts(self, tmp_path):
        repo = _repo(tmp_path)
        exit_code = _run(repo.db_path, ["summary"], format_="json")
        assert exit_code == 0


class TestSummaryCommand:
    def test_summary_reflects_seeded_data(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000.5"), reserved_balance=Decimal("500.25"), updated_at=_now(),
        ))
        repo.save_position(Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.1"),
            reserved_quantity=Decimal("0"), average_entry_price=Decimal("50000"),
            realized_pnl_to_date=Decimal("0"), updated_at=_now(),
        ))
        repo.save_order(Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=_now(), updated_at=_now(),
        ))
        repo.save_portfolio_snapshot(PortfolioSnapshot(
            timestamp=_now(), cash_balance=Decimal("9500.25"), positions_value=Decimal("5000"),
            total_equity=Decimal("14500.25"), unrealized_pnl_total=Decimal("100"),
            realized_pnl_cumulative=Decimal("50"),
        ))

        exit_code = _run(repo.db_path, ["summary"], format_="json")
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "USDT"
        assert payload["total_balance"] == "10000.5"
        assert payload["reserved_balance"] == "500.25"
        assert payload["available_balance"] == "9500.25"
        assert payload["positions_value"] == "5000"
        assert payload["total_equity"] == "14500.25"
        assert payload["open_positions_count"] == 1
        assert payload["pending_orders_count"] == 1

    def test_available_balance_is_total_minus_reserved(self, tmp_path, capsys):
        """§11: available_balance se deriva únicamente como total - reserved."""
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("100"), reserved_balance=Decimal("30"), updated_at=_now(),
        ))
        _run(repo.db_path, ["summary"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert Decimal(payload["available_balance"]) == Decimal("100") - Decimal("30")

    def test_summary_never_writes(self, tmp_path):
        repo = _repo(tmp_path)
        before = repo.fetch_cash_balances()
        _run(repo.db_path, ["summary"])
        after = repo.fetch_cash_balances()
        assert before == after


def _fake_settings(database_path: str, currency: str = "USDT"):
    """Etapa 6.21: doble mínimo de `Settings` -- solo expone los dos
    campos que `portfolio_cli.py` realmente lee de `settings.paper_trading`
    (`database_path`/`currency`), nunca un `PaperTradingConfig` completo."""
    return SimpleNamespace(paper_trading=SimpleNamespace(database_path=database_path, currency=currency))


class TestCurrencyTypeValidator:
    """§8 del ticket: validación y normalización de --currency, probada
    directamente sobre el validador (sin pasar por argparse) y a través
    de main() (código de salida 2)."""

    @pytest.mark.parametrize("raw,expected", [
        ("USD", "USD"), ("usd", "USD"), ("  eur  ", "EUR"), ("USDT", "USDT"), ("clp", "CLP"), ("btc", "BTC"),
    ])
    def test_valid_values_are_normalized(self, raw, expected):
        assert portfolio_cli._currency_type(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "EU R", "EUR;", "../EUR", "123", "A", "TOOLONGCURRENCY"])
    def test_invalid_values_are_rejected(self, raw):
        with pytest.raises(argparse.ArgumentTypeError):
            portfolio_cli._currency_type(raw)

    def test_invalid_currency_via_main_exits_2_without_opening_database(self, tmp_path, monkeypatch):
        def _fail():
            raise AssertionError("load_settings() must not be called for an argparse error.")

        monkeypatch.setattr("src.utils.config.load_settings", _fail)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["summary", "--currency", "EU R"])
        assert exc_info.value.code == 2


class TestSummaryCurrencyResolution:
    """Etapa 6.21: contrato de resolución de moneda de `summary` (§2 del
    ticket) -- cuatro combinaciones de --database-path/--currency, carga
    única de configuración, aislamiento de --database-path, precedencia,
    posición de los argumentos globales y duplicados."""

    def _seed_eur_balance(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="EUR", total_balance=Decimal("5000"), reserved_balance=Decimal("100"), updated_at=_now(),
        ))
        return repo

    # --- Fila 1: sin --database-path, sin --currency -> settings.paper_trading.currency

    def test_no_database_path_no_currency_uses_configured_currency(self, tmp_path, monkeypatch, capsys):
        repo = self._seed_eur_balance(tmp_path)
        load_settings_calls = []

        def _fake_load_settings():
            load_settings_calls.append(1)
            return _fake_settings(repo.db_path, currency="EUR")

        monkeypatch.setattr("src.utils.config.load_settings", _fake_load_settings)
        exit_code = portfolio_cli.main(["summary", "--format", "json"])

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "EUR"
        assert payload["total_balance"] == "5000"
        assert payload["reserved_balance"] == "100"
        assert payload["available_balance"] == "4900"
        assert len(load_settings_calls) == 1

    def test_no_database_path_no_currency_stderr_empty_on_success(self, tmp_path, monkeypatch, capsys):
        repo = self._seed_eur_balance(tmp_path)
        monkeypatch.setattr(
            "src.utils.config.load_settings", lambda: _fake_settings(repo.db_path, currency="EUR"),
        )
        portfolio_cli.main(["summary", "--format", "json"])
        assert capsys.readouterr().err == ""

    def test_configured_usdt_matches_previous_behavior(self, tmp_path, monkeypatch, capsys):
        """§14 del ticket: no regresión -- moneda configurada USDT se
        comporta exactamente como antes de esta etapa."""
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000.5"), reserved_balance=Decimal("500.25"), updated_at=_now(),
        ))
        monkeypatch.setattr(
            "src.utils.config.load_settings", lambda: _fake_settings(repo.db_path, currency="USDT"),
        )
        exit_code = portfolio_cli.main(["summary", "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "USDT"
        assert payload["total_balance"] == "10000.5"
        assert payload["reserved_balance"] == "500.25"
        assert payload["available_balance"] == "9500.25"

    # --- Fila 2: sin --database-path, con --currency -> --currency

    def test_no_database_path_with_currency_uses_explicit_currency(self, tmp_path, monkeypatch, capsys):
        repo = self._seed_eur_balance(tmp_path)
        monkeypatch.setattr(
            "src.utils.config.load_settings", lambda: _fake_settings(repo.db_path, currency="USDT"),
        )
        exit_code = portfolio_cli.main(["summary", "--currency", "EUR", "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "EUR"
        assert payload["total_balance"] == "5000"

    def test_explicit_currency_wins_over_configured_currency(self, tmp_path, monkeypatch, capsys):
        """§18 del ticket: precedencia explícita -- settings dice USDT,
        --currency dice EUR -> gana EUR, sin tocar la configuración."""
        repo = self._seed_eur_balance(tmp_path)
        monkeypatch.setattr(
            "src.utils.config.load_settings", lambda: _fake_settings(repo.db_path, currency="USDT"),
        )
        exit_code = portfolio_cli.main(["--currency", "EUR", "summary", "--format", "json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "EUR"

    # --- Fila 3: con --database-path, sin --currency -> "USDT" (compatibilidad)

    def test_database_path_without_currency_keeps_usdt_compatibility(self, tmp_path, monkeypatch):
        """§16/§17 del ticket: compatibilidad histórica -- con
        --database-path explícito y sin --currency, se mantiene USDT
        (aunque la base solo tenga EUR), y load_settings() nunca se llama."""
        repo = self._seed_eur_balance(tmp_path)

        def _fail():
            raise AssertionError("load_settings() must not be called with --database-path explicit.")

        monkeypatch.setattr("src.utils.config.load_settings", _fail)
        exit_code = _run(repo.db_path, ["summary"], format_="json")
        assert exit_code == 0

    def test_database_path_without_currency_shows_null_balance_for_eur_only_db(self, tmp_path, capsys):
        repo = self._seed_eur_balance(tmp_path)
        exit_code = _run(repo.db_path, ["summary"], format_="json")
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "USDT"
        assert payload["total_balance"] is None
        assert payload["reserved_balance"] is None
        assert payload["available_balance"] is None

    def test_database_path_with_usdt_data_and_no_currency_still_works(self, tmp_path, capsys):
        """§16 del ticket: base USDT + --database-path sin --currency ->
        resultados históricos correctos (nunca null)."""
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        exit_code = _run(repo.db_path, ["summary"], format_="json")
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "USDT"
        assert payload["total_balance"] == "10000"

    # --- Fila 4: con --database-path, con --currency -> --currency

    def test_database_path_with_currency_resolves_correct_balance(self, tmp_path, monkeypatch):
        """§15 del ticket: --database-path + --currency EUR -> datos EUR
        correctos, load_settings() nunca llamado."""
        repo = self._seed_eur_balance(tmp_path)

        def _fail():
            raise AssertionError("load_settings() must not be called with --database-path explicit.")

        monkeypatch.setattr("src.utils.config.load_settings", _fail)
        exit_code = portfolio_cli.main([
            "summary", "--database-path", repo.db_path, "--currency", "EUR", "--format", "json",
        ])
        assert exit_code == 0

    def test_database_path_with_currency_json_values(self, tmp_path, capsys):
        repo = self._seed_eur_balance(tmp_path)
        exit_code = portfolio_cli.main([
            "summary", "--database-path", repo.db_path, "--currency", "EUR", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "EUR"
        assert payload["total_balance"] == "5000"
        assert payload["reserved_balance"] == "100"
        assert payload["available_balance"] == "4900"

    # --- §19: posición antes/después del subcomando ------------------------

    def test_currency_before_and_after_subcommand_are_equivalent(self, tmp_path):
        repo = self._seed_eur_balance(tmp_path)
        exit_code_after = portfolio_cli.main([
            "summary", "--database-path", repo.db_path, "--currency", "EUR", "--format", "json",
        ])
        exit_code_before = portfolio_cli.main([
            "--currency", "EUR", "--database-path", repo.db_path, "summary", "--format", "json",
        ])
        assert exit_code_after == exit_code_before == 0

    def test_database_path_before_currency_after_subcommand(self, tmp_path, capsys):
        repo = self._seed_eur_balance(tmp_path)
        exit_code = portfolio_cli.main([
            "--database-path", repo.db_path, "summary", "--currency", "EUR", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "EUR"

    # --- §19: duplicados -- último valor gana -------------------------------

    def test_duplicated_currency_last_value_wins(self, tmp_path, capsys):
        repo = self._seed_eur_balance(tmp_path)
        exit_code = portfolio_cli.main([
            "--currency", "USDT", "summary", "--database-path", repo.db_path,
            "--currency", "EUR", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["currency"] == "EUR"

    # --- §20: otros subcomandos ignoran --currency --------------------------

    def test_balances_ignores_currency_and_lists_all_currencies(self, tmp_path, capsys):
        repo = self._seed_eur_balance(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("100"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        exit_code = portfolio_cli.main([
            "balances", "--database-path", repo.db_path, "--currency", "EUR", "--format", "json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        currencies = {row["currency"] for row in payload}
        assert currencies == {"EUR", "USDT"}

    def test_balances_with_currency_does_not_error(self, tmp_path):
        repo = self._seed_eur_balance(tmp_path)
        exit_code = portfolio_cli.main(["balances", "--database-path", repo.db_path, "--currency", "USDT"])
        assert exit_code == 0

    def test_positions_ignores_currency(self, tmp_path):
        repo = _repo(tmp_path)
        exit_code = portfolio_cli.main(["positions", "--database-path", repo.db_path, "--currency", "EUR"])
        assert exit_code == 0

    # --- Formato table sigue funcionando con la moneda resuelta -------------

    def test_table_format_shows_resolved_currency(self, tmp_path, capsys):
        repo = self._seed_eur_balance(tmp_path)
        exit_code = portfolio_cli.main([
            "summary", "--database-path", repo.db_path, "--currency", "EUR",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "currency: EUR" in out
        assert "total_balance: 5000" in out


class TestBalancesCommand:
    def test_lists_balances(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("100"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        exit_code = _run(repo.db_path, ["balances"], format_="json")
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == [{
            "currency": "USDT", "total_balance": "100", "reserved_balance": "0",
            "available_balance": "100", "updated_at": _now().isoformat(),
        }]


class TestPositionsCommand:
    def _seed(self, repo):
        repo.save_position(Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.1"),
            reserved_quantity=Decimal("0"), average_entry_price=Decimal("50000"),
            realized_pnl_to_date=Decimal("0"), updated_at=_now(),
        ))
        repo.save_position(Position(
            exchange="Binance", symbol="ETHUSDT", side=PositionSide.FLAT, quantity=Decimal("0"),
            reserved_quantity=Decimal("0"), realized_pnl_to_date=Decimal("10"), updated_at=_now(),
        ))

    def test_status_open_excludes_flat(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["positions", "--status", "open"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [p["symbol"] for p in payload] == ["BTCUSDT"]

    def test_status_flat_only_flat(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["positions", "--status", "flat"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [p["symbol"] for p in payload] == ["ETHUSDT"]

    def test_status_all_includes_both(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["positions", "--status", "all"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 2

    def test_filters_by_exchange_and_symbol(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["positions", "--symbol", "BTCUSDT"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [p["symbol"] for p in payload] == ["BTCUSDT"]

    def test_never_writes(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed(repo)
        before = repo.fetch_positions()
        _run(repo.db_path, ["positions"])
        after = repo.fetch_positions()
        assert before == after


class TestOrdersCommand:
    def _seed(self, repo):
        repo.save_order(Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=_now(), updated_at=_now(),
        ))
        repo.save_order(Order(
            id="order-2", exchange="Binance", symbol="ETHUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=Decimal("1"), status=OrderStatus.FILLED, filled_quantity=Decimal("1"),
            average_fill_price=Decimal("3000"), source=OrderSource.AI_RECOMMENDATION,
            created_at=_now(), updated_at=_now(),
        ))

    def test_filters_by_status(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["orders", "--status", "PENDING"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [o["id"] for o in payload] == ["order-1"]

    def test_filters_by_source(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["orders", "--source", "AI_RECOMMENDATION"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [o["id"] for o in payload] == ["order-2"]

    def test_invalid_status_is_argparse_error(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "orders", "--status", "NOT_A_STATUS"])
        assert exc_info.value.code == 2

    def test_invalid_source_is_argparse_error(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "orders", "--source", "NOT_A_SOURCE"])
        assert exc_info.value.code == 2

    def test_most_recent_first(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        older = _now()
        newer = datetime(2026, 6, 1, tzinfo=timezone.utc)
        repo.save_order(Order(
            id="order-old", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.NEW, source=OrderSource.MANUAL,
            created_at=older, updated_at=older,
        ))
        repo.save_order(Order(
            id="order-new", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.NEW, source=OrderSource.MANUAL,
            created_at=newer, updated_at=newer,
        ))
        _run(repo.db_path, ["orders"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [o["id"] for o in payload] == ["order-new", "order-old"]

    def test_never_writes(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed(repo)
        before = repo.fetch_orders(limit=None)
        _run(repo.db_path, ["orders"])
        after = repo.fetch_orders(limit=None)
        assert before == after


def _seed_order(repo, order_id, **overrides):
    defaults = dict(
        id=order_id, exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.NEW, source=OrderSource.MANUAL,
        created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    repo.save_order(Order(**defaults))


class TestExecutionsCommand:
    def test_filters_by_order_id(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        _seed_order(repo, "order-1", symbol="BTCUSDT")
        _seed_order(repo, "order-2", symbol="ETHUSDT")
        repo.save_execution(Execution(
            id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
            quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=_now(),
        ))
        repo.save_execution(Execution(
            id="exec-2", order_id="order-2", exchange="Binance", symbol="ETHUSDT",
            quantity=Decimal("1"), price=Decimal("3000"), fee=Decimal("3"), executed_at=_now(),
        ))
        _run(repo.db_path, ["executions", "--order-id", "order-1"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [e["id"] for e in payload] == ["exec-1"]


class TestTradesCommand:
    def test_lists_trades_with_real_fields(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        _seed_order(repo, "order-1")
        repo.save_execution(Execution(
            id="exec-exit", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
            quantity=Decimal("0.1"), price=Decimal("51000"), fee=Decimal("5"), executed_at=_now(),
        ))
        repo.save_trade(Trade(
            id="trade-1", exchange="Binance", symbol="BTCUSDT", side="LONG", quantity=Decimal("0.1"),
            entry_price=Decimal("50000"), exit_price=Decimal("51000"), gross_pnl=Decimal("100"),
            fees=Decimal("5"), net_pnl=Decimal("95"), opened_at=_now(), closed_at=_now(),
            exit_execution_id="exec-exit",
        ))
        _run(repo.db_path, ["trades"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["net_pnl"] == "95"
        assert payload[0]["gross_pnl"] == "100"


class TestSnapshotsCommand:
    def test_portfolio_type_required(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "snapshots"])
        assert exc_info.value.code == 2

    def test_portfolio_snapshots(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_portfolio_snapshot(PortfolioSnapshot(
            timestamp=_now(), cash_balance=Decimal("100"), positions_value=Decimal("0"),
            total_equity=Decimal("100"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("0"),
        ))
        _run(repo.db_path, ["snapshots", "--type", "portfolio"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["total_equity"] == "100"

    def test_pnl_snapshots(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_pnl_snapshot(PnLSnapshot(
            timestamp=_now(), exchange="Binance", symbol="BTCUSDT", position_quantity=Decimal("0.1"),
            unrealized_pnl=Decimal("10"), realized_pnl_cumulative=Decimal("5"),
        ))
        _run(repo.db_path, ["snapshots", "--type", "pnl"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["unrealized_pnl"] == "10"

    def test_never_mixes_portfolio_and_pnl_in_one_table(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_portfolio_snapshot(PortfolioSnapshot(
            timestamp=_now(), cash_balance=Decimal("100"), positions_value=Decimal("0"),
            total_equity=Decimal("100"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("0"),
        ))
        repo.save_pnl_snapshot(PnLSnapshot(
            timestamp=_now(), exchange="Binance", symbol="BTCUSDT", position_quantity=Decimal("0.1"),
            unrealized_pnl=Decimal("10"), realized_pnl_cumulative=Decimal("5"),
        ))
        _run(repo.db_path, ["snapshots", "--type", "portfolio"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert all("exchange" not in row for row in payload)


class TestInspectionsCommand:
    def _seed_run(self, repo, run_id, success):
        run = ScheduledInspectionRun(
            id=run_id, started_at=_now(), completed_at=_now(), success=success, report=None,
            previous_run_id=None, new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0,
            changed_issue_count=0, alert_count=0, error_message=None if success else "boom",
        )
        repo.save_inspection_run_transaction(run, [])

    def test_filters_by_status(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_run(repo, "run-ok", True)
        self._seed_run(repo, "run-bad", False)
        _run(repo.db_path, ["inspections", "--status", "failed"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [r["run_id"] for r in payload] == ["run-bad"]
        assert payload[0]["status"] == "failed"

    def test_field_names_adapted(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_run(repo, "run-ok", True)
        _run(repo.db_path, ["inspections"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert set(payload[0].keys()) == {
            "run_id", "status", "started_at", "finished_at", "issue_count", "alert_count", "error_message",
        }


class TestAlertsCommand:
    def _alert(self, alert_id, status, severity=IssueSeverity.WARNING, alert_type=AlertType.NEW_ISSUE):
        return InspectionAlert(
            id=alert_id, run_id="run-1", alert_type=alert_type, issue_identity=None, issue_code=None,
            severity=severity, title="t", message="m", deduplication_key=f"dedup-{alert_id}",
            status=status, delivery_attempts=0, last_error=None, created_at=_now(),
        )

    def _seed_run_and_alerts(self, repo, alerts):
        run = ScheduledInspectionRun(
            id="run-1", started_at=_now(), completed_at=_now(), success=True, report=None,
            previous_run_id=None, new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0,
            changed_issue_count=0, alert_count=len(alerts),
        )
        repo.save_inspection_run_transaction(run, alerts)

    def test_filters_by_status(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_run_and_alerts(repo, [
            self._alert("a1", AlertStatus.PENDING), self._alert("a2", AlertStatus.DELIVERED),
        ])
        _run(repo.db_path, ["alerts", "--status", "PENDING"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [a["id"] for a in payload] == ["a1"]

    def test_filters_by_severity(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_run_and_alerts(repo, [
            self._alert("a1", AlertStatus.PENDING, severity=IssueSeverity.CRITICAL),
            self._alert("a2", AlertStatus.PENDING, severity=IssueSeverity.INFO),
        ])
        _run(repo.db_path, ["alerts", "--severity", "CRITICAL"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [a["id"] for a in payload] == ["a1"]

    def test_filters_by_type(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_run_and_alerts(repo, [
            self._alert("a1", AlertStatus.PENDING, alert_type=AlertType.NEW_ISSUE),
            self._alert("a2", AlertStatus.PENDING, alert_type=AlertType.RESOLVED_ISSUE),
        ])
        _run(repo.db_path, ["alerts", "--type", "RESOLVED_ISSUE"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [a["id"] for a in payload] == ["a2"]

    def test_does_not_include_nonexistent_updated_at_field(self, tmp_path, capsys):
        """InspectionAlert no tiene updated_at -- no debe inventarse."""
        repo = _repo(tmp_path)
        self._seed_run_and_alerts(repo, [self._alert("a1", AlertStatus.PENDING)])
        _run(repo.db_path, ["alerts"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert "updated_at" not in payload[0]


class TestDeliveriesCommand:
    def _seed(self, repo):
        run = ScheduledInspectionRun(
            id="run-1", started_at=_now(), completed_at=_now(), success=True, report=None,
            previous_run_id=None, new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0,
            changed_issue_count=0, alert_count=1,
        )
        alert = InspectionAlert(
            id="alert-1", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None, issue_code=None,
            severity=IssueSeverity.WARNING, title="t", message="m", deduplication_key="dedup-alert-1",
            status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
        )
        repo.save_inspection_run_transaction(run, [alert])
        repo.upsert_alert_channel_delivery(InspectionAlertChannelDelivery(
            alert_id="alert-1", channel_name="TelegramNotificationChannel", status=AlertStatus.DELIVERED,
            delivery_attempts=1, last_error=None, delivered_at=_now(), updated_at=_now(),
        ))
        repo.upsert_alert_channel_delivery(InspectionAlertChannelDelivery(
            alert_id="alert-1", channel_name="WebhookNotificationChannel", status=AlertStatus.PENDING,
            delivery_attempts=1, last_error="Webhook request failed (HTTP 500).", delivered_at=None,
            updated_at=_now(),
        ))

    def test_filters_by_alert_id(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["deliveries", "--alert-id", "alert-1"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 2

    def test_filters_by_channel(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["deliveries", "--channel", "WebhookNotificationChannel"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [d["channel_name"] for d in payload] == ["WebhookNotificationChannel"]

    def test_filters_by_status(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["deliveries", "--status", "PENDING"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [d["channel_name"] for d in payload] == ["WebhookNotificationChannel"]

    def test_last_error_already_sanitized_is_displayed(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed(repo)
        _run(repo.db_path, ["deliveries", "--channel", "WebhookNotificationChannel"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["last_error"] == "Webhook request failed (HTTP 500)."

    def test_never_retries_or_constructs_transports(self, tmp_path):
        """§19: nunca reintenta entregas, nunca construye transportes --
        confirmado por ausencia de import/construcción, ver TestIsolation."""
        repo = _repo(tmp_path)
        self._seed(repo)
        before = repo.fetch_alert_channel_deliveries("alert-1")
        _run(repo.db_path, ["deliveries"])
        after = repo.fetch_alert_channel_deliveries("alert-1")
        assert before == after


class TestReconciliationAuditsCommand:
    def _audit(self, audit_id, success):
        return ReconciliationAuditRecord(
            id=audit_id, started_at=_now(), completed_at=_now(), dry_run=True, success=success,
            issue_count=1, repaired_count=1 if success else 0, report_json="{}", operations_json="[]",
            error_message=None if success else "controlled failure",
        )

    def test_filters_by_run_id(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_reconciliation_audit_record(self._audit("audit-1", True))
        repo.save_reconciliation_audit_record(self._audit("audit-2", True))
        _run(repo.db_path, ["reconciliation-audits", "--run-id", "audit-1"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [a["id"] for a in payload] == ["audit-1"]

    def test_filters_by_status_success_failure(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_reconciliation_audit_record(self._audit("audit-ok", True))
        repo.save_reconciliation_audit_record(self._audit("audit-bad", False))
        _run(repo.db_path, ["reconciliation-audits", "--status", "failure"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert [a["id"] for a in payload] == ["audit-bad"]

    def test_never_calls_repair(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_reconciliation_audit_record(self._audit("audit-1", True))
        before = repo.fetch_cash_balances()
        _run(repo.db_path, ["reconciliation-audits"])
        after = repo.fetch_cash_balances()
        assert before == after


class TestLimitContract:
    """§21: entero positivo, 0 rechazado, negativo rechazado, default
    50, máximo 1000."""

    def test_default_limit_is_50(self):
        assert portfolio_cli.DEFAULT_LIMIT == 50

    def test_maximum_limit_is_1000(self):
        assert portfolio_cli.MAX_LIMIT == 1000

    @pytest.mark.parametrize("bad_limit", ["0", "-1", "-100"])
    def test_rejects_non_positive_limit(self, tmp_path, bad_limit):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "orders", "--limit", bad_limit])
        assert exc_info.value.code == 2

    def test_rejects_limit_above_maximum(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "orders", "--limit", "1001"])
        assert exc_info.value.code == 2

    def test_accepts_limit_at_maximum(self, tmp_path):
        repo = _repo(tmp_path)
        assert _run(repo.db_path, ["orders", "--limit", "1000"]) == 0

    def test_limit_actually_bounds_results(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        for i in range(5):
            repo.save_order(Order(
                id=f"order-{i}", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.NEW,
                source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
            ))
        _run(repo.db_path, ["orders", "--limit", "2"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 2


class TestTableFormat:
    def test_none_renders_as_dash(self):
        assert portfolio_cli._format_value_for_table(None) == "-"

    def test_decimal_renders_exactly(self):
        assert portfolio_cli._format_value_for_table(Decimal("10000.123456789")) == "10000.123456789"

    def test_datetime_renders_iso8601(self):
        value = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
        assert portfolio_cli._format_value_for_table(value) == value.isoformat()

    def test_long_text_truncates_deterministically(self):
        text = "x" * 200
        result = portfolio_cli._format_value_for_table(text)
        assert len(result) == portfolio_cli._TABLE_MAX_TEXT_LENGTH
        assert result.endswith("...")

    def test_short_id_never_truncated(self):
        short_id = "order-abc123"
        assert portfolio_cli._format_value_for_table(short_id) == short_id

    def test_zero_rows_message(self):
        assert portfolio_cli.render_table([], ["id"]) == "No records found."

    def test_table_has_header_and_separator(self):
        rows = [{"id": "a1", "value": Decimal("1")}]
        rendered = portfolio_cli.render_table(rows, ["id", "value"])
        lines = rendered.splitlines()
        assert lines[0].startswith("id")
        assert set(lines[1].replace(" ", "")) == {"-"}


class TestJsonFormat:
    def test_valid_json_output(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        _run(repo.db_path, ["balances"], format_="json")
        output = capsys.readouterr().out
        json.loads(output)  # no debe lanzar

    def test_decimal_becomes_string_not_float(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("0.1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        _run(repo.db_path, ["balances"], format_="json")
        raw_output = capsys.readouterr().out
        assert '"0.1"' in raw_output  # nunca 0.1 sin comillas (float)

    def test_none_becomes_null(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        _run(repo.db_path, ["summary"], format_="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload["total_balance"] is None

    def test_deterministic_list_order(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        for i in range(3):
            repo.save_order(Order(
                id=f"order-{i}", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.NEW,
                source=OrderSource.MANUAL, created_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
                updated_at=_now(),
            ))
        _run(repo.db_path, ["orders"], format_="json")
        payload_1 = capsys.readouterr().out
        _run(repo.db_path, ["orders"], format_="json")
        payload_2 = capsys.readouterr().out
        assert payload_1 == payload_2

    def test_no_logs_mixed_into_stdout(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        _run(repo.db_path, ["summary"], format_="json")
        output = capsys.readouterr().out
        json.loads(output)  # el stdout completo debe ser JSON puro, nada más


class TestNoWriteGuarantee:
    """§27: garantía integral de no-escritura -- ejecuta TODOS los
    subcomandos y confirma que el contenido, el schema y los archivos
    auxiliares son exactamente iguales antes y después."""

    def _snapshot(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            schema = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"
            ).fetchall()
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            contents = {}
            for table in sorted(tables):
                contents[table] = conn.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            conn.close()
        return schema, contents

    def test_all_subcommands_leave_database_untouched(self, tmp_path):
        repo = _repo(tmp_path)
        now = _now()
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("500"), updated_at=now,
        ))
        repo.save_position(Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.1"),
            reserved_quantity=Decimal("0"), average_entry_price=Decimal("50000"),
            realized_pnl_to_date=Decimal("0"), updated_at=now,
        ))
        repo.save_order(Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=now, updated_at=now,
        ))
        repo.save_execution(Execution(
            id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
            quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=now,
        ))
        repo.save_trade(Trade(
            id="trade-1", exchange="Binance", symbol="BTCUSDT", side="LONG", quantity=Decimal("0.1"),
            entry_price=Decimal("49000"), exit_price=Decimal("50000"), gross_pnl=Decimal("100"),
            fees=Decimal("5"), net_pnl=Decimal("95"), opened_at=now, closed_at=now, exit_execution_id="exec-1",
        ))
        repo.save_portfolio_snapshot(PortfolioSnapshot(
            timestamp=now, cash_balance=Decimal("9500"), positions_value=Decimal("5000"),
            total_equity=Decimal("14500"), unrealized_pnl_total=Decimal("100"), realized_pnl_cumulative=Decimal("95"),
        ))
        repo.save_pnl_snapshot(PnLSnapshot(
            timestamp=now, exchange="Binance", symbol="BTCUSDT", position_quantity=Decimal("0.1"),
            unrealized_pnl=Decimal("10"), realized_pnl_cumulative=Decimal("95"),
        ))
        run = ScheduledInspectionRun(
            id="run-1", started_at=now, completed_at=now, success=True, report=None,
            previous_run_id=None, new_issue_count=0, resolved_issue_count=0, persistent_issue_count=0,
            changed_issue_count=0, alert_count=1,
        )
        alert = InspectionAlert(
            id="alert-1", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=None, issue_code=None,
            severity=IssueSeverity.WARNING, title="t", message="m", deduplication_key="dedup-1",
            status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=now,
        )
        repo.save_inspection_run_transaction(run, [alert])
        repo.upsert_alert_channel_delivery(InspectionAlertChannelDelivery(
            alert_id="alert-1", channel_name="TelegramNotificationChannel", status=AlertStatus.PENDING,
            delivery_attempts=0, last_error=None, delivered_at=None, updated_at=now,
        ))
        repo.save_reconciliation_audit_record(ReconciliationAuditRecord(
            id="audit-1", started_at=now, completed_at=now, dry_run=True, success=True,
            issue_count=0, repaired_count=0, report_json="{}", operations_json="[]",
        ))

        db_path = repo.db_path
        before_schema, before_contents = self._snapshot(db_path)
        before_size = __import__("os").path.getsize(db_path)
        before_dir_listing = set(__import__("os").listdir(tmp_path))

        commands = [
            ["summary"], ["balances"], ["positions"], ["orders"], ["executions"], ["trades"],
            ["snapshots", "--type", "portfolio"], ["snapshots", "--type", "pnl"],
            ["inspections"], ["alerts"], ["deliveries"], ["reconciliation-audits"],
        ]
        for command in commands:
            for format_ in ("table", "json"):
                exit_code = _run(db_path, command, format_=format_)
                assert exit_code == 0, f"{command} ({format_}) failed with exit code {exit_code}"

        after_schema, after_contents = self._snapshot(db_path)
        after_size = __import__("os").path.getsize(db_path)
        after_dir_listing = set(__import__("os").listdir(tmp_path))

        assert before_schema == after_schema
        assert before_contents == after_contents
        assert before_size == after_size
        assert before_dir_listing == after_dir_listing  # sin -wal/-shm ni ningún archivo nuevo
        assert not any(name.endswith(("-wal", "-shm")) for name in after_dir_listing)


class TestReadOnlyConnectionRejectsWrites:
    """§28: la conexión read-only usada por la CLI rechaza una escritura
    real -- verificado a través del propio componente de consulta (la
    función interna, no una API pública nueva creada solo para esto)."""

    def test_write_attempt_is_rejected_by_sqlite(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        conn = portfolio_cli._open_readonly_connection(repo.db_path)
        try:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                conn.execute(
                    "INSERT INTO paper_trading_cash_balances (currency, total_balance, reserved_balance, updated_at) "
                    "VALUES ('EUR', '1', '0', '2026-01-01T00:00:00+00:00')"
                )
            assert "readonly" in str(exc_info.value).lower()
        finally:
            conn.close()

        # La base nunca cambió: la fila EUR nunca se insertó.
        assert repo.get_cash_balance("EUR") is None


class TestIsolation:
    """§30: la CLI no debe importar motores/servicios de escritura/
    scheduler/transportes -- verificado con `ast`, no búsqueda textual
    (que fallaría con docstrings que mencionan esos mismos nombres)."""

    _FORBIDDEN_NAMES = {
        "RiskEngine", "FillEngine", "PositionEngine", "ReservationEngine", "PnLEngine",
        "PaperTradingService", "AlertDeliveryService", "InspectionJob", "InspectionScheduler",
        "ReconciliationService", "CompositeNotificationChannel",
    }
    _FORBIDDEN_MODULES = {
        "risk_engine", "fill_engine", "position_engine", "reservation_engine", "pnl_engine",
        "service", "alert_delivery_service", "inspection_job", "inspection_scheduler",
        "reconciliation_service", "notification_channels",
        "telegram_transport", "slack_transport", "email_transport", "webhook_transport",
        "composition", "application",
    }

    @staticmethod
    def _parse_imports():
        source = open(portfolio_cli.__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        imported_names = set()
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[-1]
                imported_modules.add(module)
                for alias in node.names:
                    imported_names.add(alias.name)
        return imported_names, imported_modules

    def test_no_forbidden_class_names_imported(self):
        imported_names, _ = self._parse_imports()
        overlap = imported_names & self._FORBIDDEN_NAMES
        assert not overlap, f"forbidden classes imported: {overlap}"

    def test_no_forbidden_modules_imported(self):
        _, imported_modules = self._parse_imports()
        overlap = imported_modules & self._FORBIDDEN_MODULES
        assert not overlap, f"forbidden modules imported: {overlap}"

    def test_does_not_import_dashboard(self):
        _, imported_modules = self._parse_imports()
        assert "dashboard" not in imported_modules
        source = open(portfolio_cli.__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "dashboard" not in node.module

    def test_only_stdlib_and_paper_trading_readonly_modules_imported(self):
        _, imported_modules = self._parse_imports()
        allowed_stdlib = {
            "argparse", "json", "sqlite3", "sys", "decimal", "datetime", "enum", "pathlib", "typing",
        }
        allowed_project = {
            "alert_models", "enums", "reconciliation_models", "serialization", "config", "portfolio_cli",
        }
        unexpected = imported_modules - allowed_stdlib - allowed_project
        assert not unexpected, f"unexpected imports: {unexpected}"

    def test_never_calls_init_or_write_methods(self):
        """Auditoría textual complementaria (no sustituye el análisis
        AST de imports): confirma ausencia de los patrones de escritura
        explícitamente prohibidos en el propio código (no en docstrings
        -- se filtran las líneas de comentario/docstring de forma
        simple buscando únicamente en líneas de código real)."""
        source = open(portfolio_cli.__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        call_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
        forbidden_calls = {
            "init", "save_order", "save_execution", "save_trade", "save_position", "save_cash_balance",
            "save_fill_transaction", "save_order_acceptance_transaction", "save_order_cancellation_transaction",
            "save_reconciliation_transaction", "save_reconciliation_audit_record", "save_inspection_run_transaction",
            "update_inspection_alert_delivery", "upsert_alert_channel_delivery", "accept_market_order",
            "fill_pending_order", "cancel_pending_order", "repair", "deliver_pending_alerts", "run_once",
            "run_forever", "deliver",
        }
        overlap = call_names & forbidden_calls
        assert not overlap, f"forbidden calls found in AST: {overlap}"


class TestGlobalArgumentPosition:
    """Etapa 6.18.1: `--database-path`/`--format` deben aceptarse tanto
    antes como después del subcomando, con el mismo comportamiento
    observable en ambos casos."""

    def _seed_pending_order(self, repo):
        repo.save_order(Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
            created_at=_now(), updated_at=_now(),
        ))

    # --- §11: main(), summary sin opciones propias --------------------

    def test_globals_before_subcommand(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        exit_code = portfolio_cli.main([
            "--database-path", repo.db_path, "--format", "json", "summary",
        ])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["currency"] == "USDT"
        assert captured.err == ""

    def test_globals_after_subcommand(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        exit_code = portfolio_cli.main([
            "summary", "--database-path", repo.db_path, "--format", "json",
        ])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["currency"] == "USDT"
        assert captured.err == ""

    def test_both_positions_produce_equivalent_output(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_pending_order(repo)

        portfolio_cli.main(["--database-path", repo.db_path, "--format", "json", "summary"])
        output_before = capsys.readouterr().out

        portfolio_cli.main(["summary", "--database-path", repo.db_path, "--format", "json"])
        output_after = capsys.readouterr().out

        assert json.loads(output_before) == json.loads(output_after)

    # --- §12: comando con opciones propias (orders) --------------------

    def test_globals_after_subcommand_with_own_options(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_pending_order(repo)
        repo.save_order(Order(
            id="order-2", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal("0.1"), status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"), source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
        ))

        exit_code = portfolio_cli.main([
            "orders", "--database-path", repo.db_path, "--format", "json", "--status", "PENDING", "--limit", "20",
        ])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.err == ""
        payload = json.loads(captured.out)
        assert len(payload) <= 20
        assert all(order["status"] == "PENDING" for order in payload)
        assert [order["id"] for order in payload] == ["order-1"]

    def test_globals_before_subcommand_with_own_options_is_equivalent(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        self._seed_pending_order(repo)

        portfolio_cli.main([
            "orders", "--database-path", repo.db_path, "--format", "json", "--status", "PENDING", "--limit", "20",
        ])
        output_after = capsys.readouterr().out

        portfolio_cli.main([
            "--database-path", repo.db_path, "--format", "json", "orders", "--status", "PENDING", "--limit", "20",
        ])
        output_before = capsys.readouterr().out

        assert json.loads(output_before) == json.loads(output_after)

    # --- §13: formato por defecto (table) en ambas posiciones ----------

    def test_default_format_is_table_when_globals_after_subcommand(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        exit_code = portfolio_cli.main(["summary", "--database-path", repo.db_path])
        captured = capsys.readouterr()
        assert exit_code == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(captured.out)
        assert "currency: USDT" in captured.out

    def test_default_format_is_table_when_globals_before_subcommand(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        exit_code = portfolio_cli.main(["--database-path", repo.db_path, "summary"])
        captured = capsys.readouterr()
        assert exit_code == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(captured.out)
        assert "currency: USDT" in captured.out

    # --- §14: resolución de configuración, en ambas posiciones ---------

    def test_explicit_path_after_subcommand_never_calls_load_settings(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)

        def _fail(*args, **kwargs):
            raise AssertionError("load_settings() must not be called when --database-path is explicit.")

        monkeypatch.setattr("src.utils.config.load_settings", _fail)
        exit_code = portfolio_cli.main(["summary", "--database-path", repo.db_path])
        assert exit_code == 0

    def test_explicit_path_before_subcommand_never_calls_load_settings(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)

        def _fail(*args, **kwargs):
            raise AssertionError("load_settings() must not be called when --database-path is explicit.")

        monkeypatch.setattr("src.utils.config.load_settings", _fail)
        exit_code = portfolio_cli.main(["--database-path", repo.db_path, "summary"])
        assert exit_code == 0

    # --- §15: subprocess real ------------------------------------------

    def test_subprocess_summary_globals_after_subcommand(self, tmp_path):
        repo = _repo(tmp_path)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.paper_trading.portfolio_cli",
                "summary", "--database-path", repo.db_path, "--format", "json",
            ],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert payload["currency"] == "USDT"

    def test_subprocess_summary_with_explicit_currency(self, tmp_path):
        """Etapa 6.21, §25: consulta real vía subprocess, únicamente con
        --database-path (nunca la configuración real), confirmando datos
        EUR con --currency."""
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="EUR", total_balance=Decimal("5000"), reserved_balance=Decimal("100"), updated_at=_now(),
        ))
        result = subprocess.run(
            [
                sys.executable, "-m", "src.paper_trading.portfolio_cli",
                "summary", "--database-path", repo.db_path, "--currency", "EUR", "--format", "json",
            ],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert payload["currency"] == "EUR"
        assert payload["total_balance"] == "5000"
        assert payload["reserved_balance"] == "100"
        assert payload["available_balance"] == "4900"

    def test_subprocess_orders_globals_after_subcommand_with_own_options(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed_pending_order(repo)
        result = subprocess.run(
            [
                sys.executable, "-m", "src.paper_trading.portfolio_cli",
                "orders", "--database-path", repo.db_path, "--format", "json",
                "--status", "PENDING", "--limit", "20",
            ],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert [order["id"] for order in payload] == ["order-1"]

    # --- §16: errores de argumentos, en ambas posiciones ----------------

    def test_invalid_format_after_subcommand_exits_2(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["summary", "--database-path", repo.db_path, "--format", "xml"])
        assert exc_info.value.code == 2

    def test_invalid_limit_zero_after_subcommand_exits_2(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["orders", "--database-path", repo.db_path, "--limit", "0"])
        assert exc_info.value.code == 2

    def test_invalid_limit_over_maximum_after_subcommand_exits_2(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["orders", "--database-path", repo.db_path, "--limit", "1001"])
        assert exc_info.value.code == 2

    def test_invalid_status_before_subcommand_exits_2(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            portfolio_cli.main(["--database-path", repo.db_path, "orders", "--status", "INVALID"])
        assert exc_info.value.code == 2

    # --- §8: argumentos duplicados: el último valor gana ----------------

    def test_duplicated_format_last_value_wins(self, tmp_path, capsys):
        repo = _repo(tmp_path)
        exit_code = portfolio_cli.main([
            "--format", "table", "summary", "--database-path", repo.db_path, "--format", "json",
        ])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)  # si "table" hubiera ganado, esto lanzaría JSONDecodeError
        assert payload["currency"] == "USDT"

    def test_duplicated_database_path_last_value_wins(self, tmp_path, capsys):
        repo_a = _repo(tmp_path / "a")
        (tmp_path / "b").mkdir()
        repo_b_path = str(tmp_path / "b" / "test.db")
        repo_b = SQLitePaperTradingRepository(repo_b_path)
        repo_b.init()
        repo_b.save_cash_balance(CashBalance(
            currency="EUR", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))

        exit_code = portfolio_cli.main([
            "--database-path", repo_a.db_path, "balances", "--database-path", repo_b_path, "--format", "json",
        ])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert [b["currency"] for b in payload] == ["EUR"]  # repo_b (el último valor) ganó

    # --- §10: ayuda principal y por subcomando --------------------------

    def test_subcommand_help_includes_global_arguments(self, capsys):
        with pytest.raises(SystemExit):
            portfolio_cli.main(["orders", "--help"])
        output = capsys.readouterr().out
        assert "--database-path" in output
        assert "--format" in output
        assert "--status" in output
        assert "--source" in output
        assert "--limit" in output
        assert "--exchange" in output
        assert "--symbol" in output

    def test_main_help_includes_global_arguments(self, capsys):
        with pytest.raises(SystemExit):
            portfolio_cli.main(["--help"])
        output = capsys.readouterr().out
        assert "--database-path" in output
        assert "--format" in output


class TestReadOnlyGuaranteesAfterParserFix:
    """Etapa 6.18.1, §17: la corrección del parser no debe alterar
    ninguna garantía read-only -- reconfirmación puntual usando la
    nueva posición (globales después del subcomando)."""

    def test_missing_database_still_exits_4_with_globals_after_subcommand(self, tmp_path):
        db_path = tmp_path / "missing.db"
        exit_code = portfolio_cli.main(["summary", "--database-path", str(db_path)])
        assert exit_code == 4
        assert not db_path.exists()

    def test_readonly_connection_still_rejects_writes(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("1"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        conn = portfolio_cli._open_readonly_connection(repo.db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO paper_trading_cash_balances (currency, total_balance, reserved_balance, updated_at) "
                    "VALUES ('EUR', '1', '0', '2026-01-01T00:00:00+00:00')"
                )
        finally:
            conn.close()

    def test_no_write_guarantee_with_globals_after_subcommand(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("100"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))
        before = repo.fetch_cash_balances()

        for command in [
            ["summary"], ["balances"], ["orders"], ["positions", "--status", "open"],
        ]:
            portfolio_cli.main([*command, "--database-path", repo.db_path, "--format", "json"])

        after = repo.fetch_cash_balances()
        assert before == after
