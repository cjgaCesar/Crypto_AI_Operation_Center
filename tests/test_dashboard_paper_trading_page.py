"""
Pruebas para src/dashboard/pages/paper_trading.py, usando
streamlit.testing.v1.AppTest para ejecutar render() de verdad contra una
base SQLite temporal (Etapa 6.6). Mismo patrón que
tests/test_dashboard_signals_page.py.

Foco explícito de esta suite: además de "la página carga y muestra lo
esperado", confirma la garantía read-only a nivel de página (sin
botones BUY/SELL, sin formulario de órdenes, sin importar
PaperTradingApplication/PaperTradingService de ejecución).
"""

from datetime import datetime, timezone
from decimal import Decimal

from streamlit.testing.v1 import AppTest

from src.dashboard.paper_trading_repository import RepositoryPaperTradingDashboardRepository
from src.dashboard.paper_trading_service import PaperTradingDashboardService
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.models import CashBalance, Execution, Order, PortfolioSnapshot, Position
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _service_for(db_path: str, enabled: bool = True) -> PaperTradingDashboardService:
    underlying = SQLitePaperTradingRepository(db_path)
    dashboard_repo = RepositoryPaperTradingDashboardRepository(underlying, db_path)
    return PaperTradingDashboardService(repository=dashboard_repo, enabled=enabled, currency="USDT")


def _render_paper_trading(service):
    from src.dashboard.pages import paper_trading
    paper_trading.render(service)


def _run(service, timeout=30):
    at = AppTest.from_function(_render_paper_trading, args=(service,))
    at.run(timeout=timeout)
    return at


def _populated_db(tmp_path) -> str:
    db_path = str(tmp_path / "populated.db")
    repo = SQLitePaperTradingRepository(db_path)
    repo.init()
    now = _now()
    repo.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=now))
    order = Order(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.FILLED,
        filled_quantity=Decimal("0.1"), average_fill_price=Decimal("50000"),
        source=OrderSource.MANUAL, created_at=now, updated_at=now,
    )
    repo.save_order(order)
    repo.save_execution(Execution(
        id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
        quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=now,
    ))
    repo.save_position(Position(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.1"),
        average_entry_price=Decimal("50000"), updated_at=now, opened_at=now,
    ))
    repo.save_portfolio_snapshot(PortfolioSnapshot(
        timestamp=now, cash_balance=Decimal("4995"), positions_value=Decimal("5000"),
        total_equity=Decimal("9995"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("0"),
    ))
    return db_path


def _empty_db(tmp_path) -> str:
    db_path = str(tmp_path / "empty.db")
    SQLitePaperTradingRepository(db_path).init()
    return db_path


def _uninitialized_db(tmp_path) -> str:
    return str(tmp_path / "does_not_exist.db")


class TestPageRendering:
    def test_renders_without_exception_against_uninitialized_database(self, tmp_path):
        at = _run(_service_for(_uninitialized_db(tmp_path)))
        assert not at.exception

    def test_renders_without_exception_against_populated_database(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        assert not at.exception

    def test_shows_not_initialized_message(self, tmp_path):
        at = _run(_service_for(_uninitialized_db(tmp_path)))
        assert any("aún no ha sido inicializado" in info.value for info in at.info)

    def test_shows_content_when_populated(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        assert any("Paper Trading" in title.value for title in at.title)

    def test_empty_but_initialized_database_does_not_crash(self, tmp_path):
        at = _run(_service_for(_empty_db(tmp_path)))
        assert not at.exception


class TestDisabledState:
    def test_shows_disabled_warning(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path), enabled=False))
        assert len(at.warning) >= 1
        assert any("deshabilitado" in warning.value for warning in at.warning)

    def test_still_shows_historical_data_when_disabled(self, tmp_path):
        """enabled=false debe seguir permitiendo leer datos históricos ya
        existentes (Paso 19), no ocultarlos por completo."""
        at = _run(_service_for(_populated_db(tmp_path), enabled=False))
        assert not at.exception
        assert len(at.tabs) > 0

    def test_no_warning_when_enabled(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path), enabled=True))
        assert not any("deshabilitado" in warning.value for warning in at.warning)


class TestReadOnlyGuarantees:
    def test_no_buy_sell_buttons(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        button_labels = {button.label for button in at.button}
        assert "BUY" not in button_labels
        assert "SELL" not in button_labels
        assert "Comprar" not in button_labels
        assert "Vender" not in button_labels

    def test_no_order_form(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        # AppTest expone los formularios bajo `at.get("form")`; una página
        # de solo lectura no debe declarar ningún st.form.
        assert len(at.get("form")) == 0

    def test_page_source_does_not_import_execution_layer(self):
        """Usa el AST (no una búsqueda de texto) para que las menciones en
        docstrings/comentarios -- legítimas para documentar qué NO se usa,
        ver Paso 24 de la Etapa 6.6 -- no produzcan falsos positivos:
        solo se inspeccionan nodos Import/ImportFrom y llamadas (Call)
        reales."""
        import ast

        import src.dashboard.pages.paper_trading as module
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())

        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_names.update(alias.name for alias in node.names)

        forbidden_imports = {
            "PaperTradingApplication", "PaperTradingService", "FillEngine",
            "PositionEngine", "RiskEngine", "PnLEngine", "sqlite3",
        }
        assert imported_names.isdisjoint(forbidden_imports)

        called_names = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        forbidden_calls = {"submit_manual_market_order", "submit_market_order"}
        assert called_names.isdisjoint(forbidden_calls)
        assert not any(name.startswith("save_") for name in called_names)

    def test_page_does_not_write_anything(self, tmp_path):
        db_path = _populated_db(tmp_path)
        import sqlite3

        def _counts():
            conn = sqlite3.connect(db_path)
            try:
                tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
            finally:
                conn.close()

        before = _counts()
        _run(_service_for(db_path))
        _run(_service_for(db_path))
        after = _counts()
        assert before == after


class TestFiltersAndSections:
    def test_expander_with_filters_is_present(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        assert len(at.expander) >= 1

    def test_tabs_render(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        assert len(at.tabs) > 0

    def test_rerun_after_filter_change_reflects_new_view(self, tmp_path):
        at = _run(_service_for(_populated_db(tmp_path)))
        text_inputs = at.text_input
        assert len(text_inputs) >= 2  # exchange, símbolo
        text_inputs[1].set_value("DOESNOTEXIST").run()
        assert not at.exception
