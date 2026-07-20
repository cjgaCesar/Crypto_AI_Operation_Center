"""
Pruebas para src/dashboard/paper_trading_service.py
(PaperTradingDashboardService), Etapa 6.6.

Usa SQLitePaperTradingRepository real (tmp_path) envuelto en
RepositoryPaperTradingDashboardRepository -- no un Fake -- para
verificar que el Service arma la vista de presentación correctamente a
partir de datos reales, sin recalcular PnL/riesgo/posiciones.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.dashboard.paper_trading_models import (
    PNL_CONSISTENT,
    PNL_INCONSISTENT,
    PNL_NO_TRADES,
    PNL_SUMMARY_ALL_CONSISTENT,
    PNL_SUMMARY_HAS_INCONSISTENCIES,
    PNL_SUMMARY_NO_DATA,
)
from src.dashboard.paper_trading_repository import RepositoryPaperTradingDashboardRepository
from src.dashboard.paper_trading_service import PaperTradingDashboardService
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide
from src.paper_trading.models import CashBalance, Execution, Order, PortfolioSnapshot, Position, Trade
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _service(tmp_path, enabled=True, currency="USDT") -> tuple[PaperTradingDashboardService, SQLitePaperTradingRepository]:
    db_path = str(tmp_path / "test.db")
    underlying = SQLitePaperTradingRepository(db_path)
    underlying.init()
    dashboard_repo = RepositoryPaperTradingDashboardRepository(underlying, db_path)
    service = PaperTradingDashboardService(repository=dashboard_repo, enabled=enabled, currency=currency)
    return service, underlying


def _order(**overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.1"), average_fill_price=Decimal("50000"),
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


def _position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


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


class TestUninitialized:
    def test_returns_not_initialized_when_database_missing(self, tmp_path):
        db_path = str(tmp_path / "missing.db")
        dashboard_repo = RepositoryPaperTradingDashboardRepository(
            SQLitePaperTradingRepository(db_path), db_path,
        )
        service = PaperTradingDashboardService(repository=dashboard_repo, enabled=True, currency="USDT")
        page = service.get_page()
        assert page.initialized is False
        assert page.message == "Paper Trading aún no ha sido inicializado."
        assert page.positions == []
        assert page.orders == []


class TestOverview:
    def test_overview_uses_latest_snapshot(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), reserved_balance=Decimal("100"), updated_at=_now()))
        repo.save_portfolio_snapshot(
            PortfolioSnapshot(
                timestamp=_now(), cash_balance=Decimal("9900"), positions_value=Decimal("5000"),
                total_equity=Decimal("14900"), unrealized_pnl_total=Decimal("50"), realized_pnl_cumulative=Decimal("10"),
            )
        )
        page = service.get_page()
        assert page.overview.positions_value == Decimal("5000")
        assert page.overview.total_equity == Decimal("14900")
        assert page.overview.unrealized_pnl_total == Decimal("50")
        assert page.overview.realized_pnl_cumulative == Decimal("10")
        assert page.overview.has_snapshot is True

    def test_overview_without_snapshot_has_none_fields(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        page = service.get_page()
        assert page.overview.has_snapshot is False
        assert page.overview.total_equity is None
        assert page.overview.positions_value is None

    def test_available_balance_is_total_minus_reserved(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), reserved_balance=Decimal("500"), updated_at=_now()))
        page = service.get_page()
        assert page.overview.available_balance == Decimal("9500")

    def test_open_positions_count_excludes_flat(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_position(_position(exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG))
        repo.save_position(Position(exchange="Binance", symbol="ETHUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now()))
        page = service.get_page(include_flat=True)
        assert page.overview.open_positions_count == 1

    def test_total_trades_count(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade())
        page = service.get_page()
        assert page.overview.total_trades_count == 1


class TestConsistency:
    def test_all_consistent(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(net_pnl=Decimal("394.6")))
        repo.save_position(Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"),
            realized_pnl_to_date=Decimal("394.6"), updated_at=_now(),
        ))
        page = service.get_page(include_flat=True)
        assert page.overview.pnl_consistency_summary == PNL_SUMMARY_ALL_CONSISTENT
        assert page.consistency_rows[0].status == PNL_CONSISTENT

    def test_inconsistent(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(net_pnl=Decimal("394.6")))
        repo.save_position(Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"),
            realized_pnl_to_date=Decimal("999"), updated_at=_now(),
        ))
        page = service.get_page(include_flat=True)
        assert page.overview.pnl_consistency_summary == PNL_SUMMARY_HAS_INCONSISTENCIES
        assert page.consistency_rows[0].status == PNL_INCONSISTENT

    def test_no_trades_does_not_count_as_inconsistent(self, tmp_path):
        """Bug real detectado y corregido durante esta etapa: una posición
        sin trades todavía ('Sin trades') no debe disparar la alerta
        global de inconsistencia."""
        service, repo = _service(tmp_path)
        repo.save_position(_position())
        page = service.get_page()
        assert page.consistency_rows[0].status == PNL_NO_TRADES
        assert page.overview.pnl_consistency_summary == PNL_SUMMARY_ALL_CONSISTENT

    def test_no_data_when_nothing_exists(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        page = service.get_page()
        assert page.overview.pnl_consistency_summary == PNL_SUMMARY_NO_DATA
        assert page.consistency_rows == []


class TestRows:
    def test_position_rows(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_position(_position(reserved_quantity=Decimal("0.02")))
        page = service.get_page()
        assert len(page.positions) == 1
        row = page.positions[0]
        assert row.exchange == "Binance"
        assert row.symbol == "BTCUSDT"
        assert row.quantity == Decimal("0.1")
        assert row.reserved_quantity == Decimal("0.02")

    def test_order_rows(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order())
        page = service.get_page()
        assert len(page.orders) == 1
        assert page.orders[0].id == "order-1"
        assert page.orders[0].status == OrderStatus.FILLED

    def test_execution_rows_have_decimal_notional(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution(quantity=Decimal("0.1"), price=Decimal("50000")))
        page = service.get_page()
        assert len(page.executions) == 1
        assert page.executions[0].notional == Decimal("5000.0")
        assert isinstance(page.executions[0].notional, Decimal)

    def test_trade_rows_do_not_recalculate_pnl(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(gross_pnl=Decimal("400"), fees=Decimal("5.4"), net_pnl=Decimal("394.6")))
        page = service.get_page()
        assert page.trades[0].gross_pnl == Decimal("400")
        assert page.trades[0].fees == Decimal("5.4")
        assert page.trades[0].net_pnl == Decimal("394.6")


class TestChronologicalSeries:
    def test_equity_history_is_ascending(self, tmp_path):
        service, repo = _service(tmp_path)
        base = _now()
        for i in range(3):
            cash = Decimal("5000") + Decimal(i)
            repo.save_portfolio_snapshot(
                PortfolioSnapshot(
                    timestamp=base + timedelta(minutes=i), cash_balance=cash,
                    positions_value=Decimal("5000"), total_equity=cash + Decimal("5000"),
                    unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("0"),
                )
            )
        page = service.get_page()
        timestamps = [point.timestamp for point in page.equity_history]
        assert timestamps == sorted(timestamps)

    def test_symbol_pnl_distribution_sums_net_pnl(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order(id="o1", symbol="BTCUSDT"))
        repo.save_execution(_execution(id="e1", order_id="o1", symbol="BTCUSDT"))
        repo.save_trade(_trade(id="t1", symbol="BTCUSDT", exit_execution_id="e1", net_pnl=Decimal("100"), gross_pnl=Decimal("100"), fees=Decimal("0")))
        repo.save_trade(_trade(id="t2", symbol="BTCUSDT", exit_execution_id="e1", net_pnl=Decimal("50"), gross_pnl=Decimal("50"), fees=Decimal("0")))
        page = service.get_page()
        assert len(page.symbol_pnl_distribution) == 1
        assert page.symbol_pnl_distribution[0].net_pnl_sum == Decimal("150")

    def test_no_trades_means_no_distribution(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        page = service.get_page()
        assert page.symbol_pnl_distribution == []


class TestFilters:
    def test_filter_by_exchange(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order(id="o1", exchange="Binance"))
        repo.save_order(_order(id="o2", exchange="Kraken"))
        page = service.get_page(exchange="Kraken")
        assert [o.id for o in page.orders] == ["o2"]

    def test_filter_by_symbol(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order(id="o1", symbol="BTCUSDT"))
        repo.save_order(_order(id="o2", symbol="ETHUSDT"))
        page = service.get_page(symbol="ETHUSDT")
        assert [o.id for o in page.orders] == ["o2"]

    def test_filter_by_status(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order(id="o1", status=OrderStatus.PENDING, filled_quantity=Decimal("0"), average_fill_price=None))
        repo.save_order(_order(id="o2", status=OrderStatus.FILLED))
        page = service.get_page(status=OrderStatus.FILLED)
        assert [o.id for o in page.orders] == ["o2"]

    def test_empty_states_when_no_data_matches_filter(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_order(_order(symbol="BTCUSDT"))
        page = service.get_page(symbol="DOESNOTEXIST")
        assert page.orders == []


class TestNoMutationOrWrites:
    def test_does_not_mutate_input_models(self, tmp_path):
        service, repo = _service(tmp_path)
        position = _position()
        repo.save_position(position)
        original_quantity = position.quantity
        service.get_page()
        assert position.quantity == original_quantity

    def test_does_not_write_anything(self, tmp_path):
        service, repo = _service(tmp_path)
        repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        service.get_page()
        # Nada cambia: la misma consulta repetida produce el mismo resultado.
        assert repo.get_cash_balance("USDT").total_balance == Decimal("10000")
