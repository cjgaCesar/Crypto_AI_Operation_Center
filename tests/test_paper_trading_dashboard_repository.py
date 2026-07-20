"""
Pruebas para src/dashboard/paper_trading_repository.py
(RepositoryPaperTradingDashboardRepository), Etapa 6.6.

Mismo criterio que tests/test_dashboard_repository.py (Etapa 5): usa
SQLitePaperTradingRepository real con tmp_path, nunca mockea sqlite3, y
confirma explícitamente que esta capa nunca escribe (ver también
tests/test_paper_trading_dashboard_readonly.py para la garantía
integral de no-escritura).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.dashboard.models import DashboardStatus
from src.dashboard.paper_trading_repository import (
    PaperTradingDashboardRepository, RepositoryPaperTradingDashboardRepository,
)
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide
from src.paper_trading.models import CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _repo(tmp_path) -> tuple[RepositoryPaperTradingDashboardRepository, SQLitePaperTradingRepository, str]:
    db_path = str(tmp_path / "test.db")
    underlying = SQLitePaperTradingRepository(db_path)
    underlying.init()
    return RepositoryPaperTradingDashboardRepository(underlying, db_path), underlying, db_path


def _order(**overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.PENDING,
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _execution(**overrides) -> Execution:
    defaults = dict(
        id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
        quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=_now(),
    )
    defaults.update(overrides)
    return Execution(**defaults)


def _trade(**overrides) -> Trade:
    opened = _now()
    defaults = dict(
        id="trade-1", exchange="Binance", symbol="BTCUSDT", side=TradeSide.LONG,
        quantity=Decimal("0.1"), entry_price=Decimal("50000"), exit_price=Decimal("54000"),
        gross_pnl=Decimal("400"), fees=Decimal("5.4"), net_pnl=Decimal("394.6"),
        opened_at=opened, closed_at=opened + timedelta(minutes=5), exit_execution_id="exec-1",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def _position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestGetCashBalance:
    def test_reads_existing_cash_balance(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        assert dashboard_repo.get_cash_balance("USDT").total_balance == Decimal("10000")

    def test_returns_none_when_missing(self, tmp_path):
        dashboard_repo, _, _ = _repo(tmp_path)
        assert dashboard_repo.get_cash_balance("USDT") is None


class TestGetPositions:
    def test_excludes_flat_by_default(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_position(_position(exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG))
        underlying.save_position(
            Position(exchange="Binance", symbol="ETHUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now())
        )
        results = dashboard_repo.get_positions(include_flat=False)
        assert [p.symbol for p in results] == ["BTCUSDT"]

    def test_includes_flat_when_requested(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_position(_position(exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG))
        underlying.save_position(
            Position(exchange="Binance", symbol="ETHUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now())
        )
        results = dashboard_repo.get_positions(include_flat=True)
        assert len(results) == 2


class TestGetOrders:
    def test_filters_by_exchange_symbol_status(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_order(_order(id="o1", symbol="BTCUSDT", status=OrderStatus.PENDING))
        underlying.save_order(_order(id="o2", symbol="ETHUSDT", status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"), average_fill_price=Decimal("100")))
        results = dashboard_repo.get_orders(symbol="ETHUSDT", status=OrderStatus.FILLED)
        assert [o.id for o in results] == ["o2"]

    def test_limit_applies(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        base = _now()
        for i in range(3):
            underlying.save_order(_order(id=f"o{i}", created_at=base + timedelta(seconds=i), updated_at=base))
        assert len(dashboard_repo.get_orders(limit=2)) == 2


class TestGetExecutions:
    def test_filters_by_symbol(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_order(_order(id="o1", symbol="BTCUSDT"))
        underlying.save_order(_order(id="o2", symbol="ETHUSDT"))
        underlying.save_execution(_execution(id="e1", order_id="o1", symbol="BTCUSDT"))
        underlying.save_execution(_execution(id="e2", order_id="o2", symbol="ETHUSDT"))
        results = dashboard_repo.get_executions(symbol="ETHUSDT")
        assert [e.id for e in results] == ["e2"]


class TestGetTrades:
    def test_filters_by_exchange(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_order(_order())
        underlying.save_execution(_execution())
        underlying.save_trade(_trade(exchange="Binance"))
        results = dashboard_repo.get_trades(exchange="Binance")
        assert len(results) == 1


class TestGetPortfolioHistory:
    def test_reads_snapshots(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_portfolio_snapshot(
            PortfolioSnapshot(
                timestamp=_now(), cash_balance=Decimal("5000"), positions_value=Decimal("5000"),
                total_equity=Decimal("10000"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("0"),
            )
        )
        assert len(dashboard_repo.get_portfolio_history()) == 1


class TestGetPnlHistory:
    def test_reads_snapshots_for_symbol(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_pnl_snapshot(
            PnLSnapshot(
                timestamp=_now(), exchange="Binance", symbol="BTCUSDT",
                position_quantity=Decimal("0.1"), unrealized_pnl=Decimal("50"), realized_pnl_cumulative=Decimal("0"),
            )
        )
        assert len(dashboard_repo.get_pnl_history("Binance", "BTCUSDT")) == 1


class TestCalculateRealizedPnl:
    def test_delegates_to_repository(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_order(_order())
        underlying.save_execution(_execution())
        underlying.save_trade(_trade(net_pnl=Decimal("100"), gross_pnl=Decimal("100"), fees=Decimal("0")))
        assert dashboard_repo.calculate_realized_pnl() == Decimal("100")

    def test_returns_zero_when_database_missing(self, tmp_path):
        db_path = str(tmp_path / "missing.db")
        dashboard_repo = RepositoryPaperTradingDashboardRepository(SQLitePaperTradingRepository(db_path), db_path)
        assert dashboard_repo.calculate_realized_pnl() == Decimal("0")


class TestCheckPositionPnlConsistency:
    def test_consults_repository(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_order(_order())
        underlying.save_execution(_execution())
        underlying.save_trade(_trade(net_pnl=Decimal("394.6")))
        underlying.save_position(_position(realized_pnl_to_date=Decimal("394.6")))
        assert dashboard_repo.check_position_pnl_consistency("Binance", "BTCUSDT") is True

    def test_returns_false_when_database_missing(self, tmp_path):
        db_path = str(tmp_path / "missing.db")
        dashboard_repo = RepositoryPaperTradingDashboardRepository(SQLitePaperTradingRepository(db_path), db_path)
        assert dashboard_repo.check_position_pnl_consistency("Binance", "BTCUSDT") is False


class TestGetStatus:
    def test_reports_initialized_tables(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        status = dashboard_repo.get_status()
        assert status.database_exists is True
        assert all(table.exists for table in status.tables)
        assert len(status.tables) == 7

    def test_reports_missing_database(self, tmp_path):
        db_path = str(tmp_path / "missing.db")
        dashboard_repo = RepositoryPaperTradingDashboardRepository(SQLitePaperTradingRepository(db_path), db_path)
        status = dashboard_repo.get_status()
        assert status.database_exists is False
        assert all(not table.exists for table in status.tables)

    def test_reports_row_count(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        underlying.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        status = dashboard_repo.get_status()
        cash_table = next(t for t in status.tables if t.table_name == "paper_trading_cash_balances")
        assert cash_table.row_count == 1


class TestUninitializedDatabase:
    def test_all_reads_return_empty_state_without_creating_file(self, tmp_path):
        db_path = tmp_path / "does_not_exist.db"
        dashboard_repo = RepositoryPaperTradingDashboardRepository(
            SQLitePaperTradingRepository(str(db_path)), str(db_path),
        )

        assert dashboard_repo.get_cash_balance() is None
        assert dashboard_repo.get_positions() == []
        assert dashboard_repo.get_orders() == []
        assert dashboard_repo.get_executions() == []
        assert dashboard_repo.get_trades() == []
        assert dashboard_repo.get_portfolio_history() == []
        assert dashboard_repo.get_pnl_history("Binance", "BTCUSDT") == []
        assert dashboard_repo.calculate_realized_pnl() == Decimal("0")
        assert dashboard_repo.check_position_pnl_consistency("Binance", "BTCUSDT") is False
        assert not db_path.exists()

    def test_file_exists_but_no_tables_returns_empty_state(self, tmp_path):
        """Archivo SQLite ya existe (ej. creado por otro repositorio del
        proyecto), pero las tablas paper_trading_* nunca se crearon."""
        db_path = str(tmp_path / "other_tables.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_data (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        dashboard_repo = RepositoryPaperTradingDashboardRepository(
            SQLitePaperTradingRepository(db_path), db_path,
        )
        assert dashboard_repo.get_cash_balance() is None
        assert dashboard_repo.get_positions() == []
        status = dashboard_repo.get_status()
        assert status.database_exists is True
        assert all(not table.exists for table in status.tables)


class TestLimitValidation:
    def test_zero_limit_propagates_repository_error(self, tmp_path):
        """limit<=0 no es un caso de 'tabla faltante': sigue siendo un
        ValueError propagado desde PaperTradingRepository (Etapa 6.3),
        nunca ocultado."""
        dashboard_repo, underlying, _ = _repo(tmp_path)
        with pytest.raises(ValueError):
            dashboard_repo.get_orders(limit=0)

    def test_negative_limit_propagates_repository_error(self, tmp_path):
        dashboard_repo, underlying, _ = _repo(tmp_path)
        with pytest.raises(ValueError):
            dashboard_repo.get_trades(limit=-1)


class TestNoWriteMethods:
    def test_interface_does_not_declare_write_methods(self):
        public_methods = {
            name for name in dir(PaperTradingDashboardRepository)
            if not name.startswith("_") and callable(getattr(PaperTradingDashboardRepository, name))
        }
        forbidden = {
            "save_order", "save_execution", "save_trade", "save_position", "save_cash_balance",
            "save_portfolio_snapshot", "save_pnl_snapshot", "save_fill_transaction",
            "seed_initial_cash_balance", "init",
        }
        assert public_methods.isdisjoint(forbidden)

    def test_implementation_does_not_expose_write_methods(self):
        public_methods = {
            name for name in dir(RepositoryPaperTradingDashboardRepository)
            if not name.startswith("_") and callable(getattr(RepositoryPaperTradingDashboardRepository, name))
        }
        forbidden = {
            "save_order", "save_execution", "save_trade", "save_position", "save_cash_balance",
            "save_portfolio_snapshot", "save_pnl_snapshot", "save_fill_transaction",
            "seed_initial_cash_balance", "init",
        }
        assert public_methods.isdisjoint(forbidden)

    def test_does_not_change_row_counts(self, tmp_path):
        dashboard_repo, underlying, db_path = _repo(tmp_path)
        underlying.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        underlying.save_position(_position())

        import sqlite3
        def _counts():
            conn = sqlite3.connect(db_path)
            try:
                return {
                    name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in (
                        "paper_trading_orders", "paper_trading_positions", "paper_trading_cash_balances",
                    )
                }
            finally:
                conn.close()

        before = _counts()
        for _ in range(5):
            dashboard_repo.get_cash_balance()
            dashboard_repo.get_positions(include_flat=True)
            dashboard_repo.get_status()
        after = _counts()
        assert before == after
