"""
Prueba integral de no-escritura del Dashboard de Paper Trading (Etapa 6.6).

Mismo espíritu que tests/test_dashboard_readonly.py (Etapa 5), pero de
punta a punta: puebla las 7 tablas paper_trading_*, ejecuta el
repositorio + servicio + página de Dashboard, y confirma que el
contenido exacto de las 7 tablas no cambió ni una fila.

También confirma explícitamente lo que pide el Paso 21 de la Etapa 6.6:
abrir la página nunca siembra `CashBalance` (a diferencia de
`build_paper_trading_context()`, que sí lo hace y que este Dashboard
nunca debe llamar).
"""

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from streamlit.testing.v1 import AppTest

from src.dashboard.paper_trading_repository import RepositoryPaperTradingDashboardRepository
from src.dashboard.paper_trading_service import PaperTradingDashboardService
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide
from src.paper_trading.models import CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository

_PAPER_TRADING_TABLES = (
    "paper_trading_orders", "paper_trading_executions", "paper_trading_trades",
    "paper_trading_positions", "paper_trading_cash_balances",
    "paper_trading_portfolio_snapshots", "paper_trading_pnl_snapshots",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_tables(db_path: str) -> dict:
    """Todas las filas de las 7 tablas, como tuplas ordenadas -- una
    instantánea exacta y comparable del contenido completo."""
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall())
            for table in _PAPER_TRADING_TABLES
        }
    finally:
        conn.close()


def _populate_all_tables(db_path: str) -> None:
    repo = SQLitePaperTradingRepository(db_path)
    repo.init()
    now = _now()

    repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=now))

    order = Order(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.1"), average_fill_price=Decimal("50000"),
        source=OrderSource.MANUAL, created_at=now, updated_at=now,
    )
    repo.save_order(order)

    execution = Execution(
        id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
        quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=now,
    )
    repo.save_execution(execution)

    trade = Trade(
        id="trade-1", exchange="Binance", symbol="BTCUSDT", side=TradeSide.LONG,
        quantity=Decimal("0.1"), entry_price=Decimal("50000"), exit_price=Decimal("54000"),
        gross_pnl=Decimal("400"), fees=Decimal("5.4"), net_pnl=Decimal("394.6"),
        opened_at=now, closed_at=now, exit_execution_id="exec-1",
    )
    repo.save_trade(trade)

    position = Position(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"),
        realized_pnl_to_date=Decimal("394.6"), updated_at=now,
    )
    repo.save_position(position)

    repo.save_portfolio_snapshot(PortfolioSnapshot(
        timestamp=now, cash_balance=Decimal("10394.6"), positions_value=Decimal("0"),
        total_equity=Decimal("10394.6"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("394.6"),
    ))
    repo.save_pnl_snapshot(PnLSnapshot(
        timestamp=now, exchange="Binance", symbol="BTCUSDT", position_quantity=Decimal("0"),
        unrealized_pnl=Decimal("0"), realized_pnl_cumulative=Decimal("394.6"),
    ))


def _render_paper_trading(service):
    from src.dashboard.pages import paper_trading
    paper_trading.render(service)


def test_full_read_cycle_never_changes_any_table(tmp_path):
    db_path = str(tmp_path / "readonly_full.db")
    _populate_all_tables(db_path)

    tables_before = _snapshot_tables(db_path)

    dashboard_repo = RepositoryPaperTradingDashboardRepository(SQLitePaperTradingRepository(db_path), db_path)
    service = PaperTradingDashboardService(repository=dashboard_repo, enabled=True, currency="USDT")

    # Todas las consultas de lectura, varias veces.
    for _ in range(3):
        service.get_page(include_flat=True)
        dashboard_repo.get_status()
        dashboard_repo.get_cash_balance("USDT")
        dashboard_repo.get_positions(include_flat=True)
        dashboard_repo.get_orders()
        dashboard_repo.get_executions()
        dashboard_repo.get_trades()
        dashboard_repo.get_portfolio_history()
        dashboard_repo.get_pnl_history("Binance", "BTCUSDT")
        dashboard_repo.calculate_realized_pnl()
        dashboard_repo.check_position_pnl_consistency("Binance", "BTCUSDT")

    # Renderizar la página completa (patrón AppTest, ver
    # test_dashboard_paper_trading_page.py).
    at = AppTest.from_function(_render_paper_trading, args=(service,))
    at.run(timeout=30)
    assert not at.exception

    tables_after = _snapshot_tables(db_path)
    assert tables_after == tables_before


def test_dashboard_never_seeds_cash_balance(tmp_path):
    """Base con las 7 tablas paper_trading_* ya creadas (init() ya se
    ejecutó alguna vez), pero SIN CashBalance todavía -- exactamente el
    estado que build_paper_trading_context()/seed_initial_cash_balance()
    (Etapa 6.5) resolverían sembrando capital. Abrir el Dashboard NUNCA
    debe hacer eso."""
    db_path = str(tmp_path / "no_cash_balance.db")
    SQLitePaperTradingRepository(db_path).init()

    underlying = SQLitePaperTradingRepository(db_path)
    assert underlying.get_cash_balance("USDT") is None

    dashboard_repo = RepositoryPaperTradingDashboardRepository(underlying, db_path)
    service = PaperTradingDashboardService(repository=dashboard_repo, enabled=True, currency="USDT")

    at = AppTest.from_function(_render_paper_trading, args=(service,))
    at.run(timeout=30)
    assert not at.exception

    assert underlying.get_cash_balance("USDT") is None


def test_dashboard_never_creates_tables_on_uninitialized_database(tmp_path):
    db_path = tmp_path / "never_initialized.db"

    dashboard_repo = RepositoryPaperTradingDashboardRepository(
        SQLitePaperTradingRepository(str(db_path)), str(db_path),
    )
    service = PaperTradingDashboardService(repository=dashboard_repo, enabled=True, currency="USDT")

    at = AppTest.from_function(_render_paper_trading, args=(service,))
    at.run(timeout=30)
    assert not at.exception

    assert not db_path.exists()
