"""
Pruebas para src/dashboard/pages/mercado.py, usando streamlit.testing.v1.AppTest
para ejecutar render() de verdad (no solo mocks) contra una base SQLite
temporal. No se prueban detalles frágiles de HTML/CSS: solo que la página
carga sin excepciones y que el contenido esperado (precio, variación,
máximo/mínimo, timestamp, gráfico, N/D) aparece.

El selector de símbolo en sí (compartido entre páginas) vive en
src/dashboard/app.py, no en mercado.py: "cambio de símbolo" se valida
aquí llamando a render() con distintos símbolos, que es exactamente lo
que hace app.py al reconstruir la página con el símbolo elegido.
"""

from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.market_data import MarketTicker


def _ticker(symbol="BTCUSDT", price=100.0, volume=10.0) -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol=symbol, price=price, volume_24h=volume,
        price_change_percent_24h=1.5, queried_at=datetime.now(timezone.utc),
    )


def _service_for(db_path: str, symbols=("BTCUSDT",)) -> DashboardService:
    repository = SQLiteDashboardRepository(db_path)
    return DashboardService(
        repository=repository, exchange="Binance", symbols=list(symbols),
        default_history_limit=100, max_history_limit=1000,
    )


def _render_mercado(service, exchange, symbol, limit):
    from src.dashboard.pages import mercado
    mercado.render(service, exchange, symbol, limit)


def _run(service, exchange="Binance", symbol="BTCUSDT", limit=100, timeout=30):
    at = AppTest.from_function(_render_mercado, args=(service, exchange, symbol, limit))
    at.run(timeout=timeout)
    return at


def _populated_db(tmp_path, prices=(100.0, 105.0)) -> str:
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()
    for price in prices:
        repo.save([_ticker(price=price)])
    return db_path


def test_page_loads_without_exceptions_against_populated_database(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception


def test_page_shows_latest_price(tmp_path):
    db_path = _populated_db(tmp_path, prices=(100.0, 64439.56))
    at = _run(_service_for(db_path))

    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert "64,439.5600" in metric_values


def test_page_shows_absolute_and_percentage_change(tmp_path):
    db_path = _populated_db(tmp_path, prices=(100.0, 110.0))
    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "+10.00" in metric_values
    assert "+10.00%" in metric_values


def test_page_shows_period_high_and_low(tmp_path):
    db_path = _populated_db(tmp_path, prices=(100.0, 90.0, 110.0))
    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "110.0000" in metric_values
    assert "90.0000" in metric_values


def test_single_record_has_no_previous_price_but_shows_current_price(tmp_path):
    db_path = _populated_db(tmp_path, prices=(64439.56,))
    at = _run(_service_for(db_path))

    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert "64,439.5600" in metric_values
    assert "N/D" in metric_values  # variación absoluta, sin registro anterior


def test_page_shows_last_update_and_record_count(tmp_path):
    db_path = _populated_db(tmp_path, prices=(100.0, 105.0, 110.0))
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "Último dato" in caption_text
    assert "Registros disponibles: 3" in caption_text


def test_page_shows_chart_when_history_exists(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.get("plotly_chart")) == 1


def test_page_shows_message_when_no_data(tmp_path):
    db_path = str(tmp_path / "empty.db")
    SQLiteMarketDataRepository(db_path).init()

    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay precios guardados" in i.value for i in at.info)
    assert len(at.get("plotly_chart")) == 0


def test_page_handles_missing_database(tmp_path):
    db_path = str(tmp_path / "does_not_exist.db")
    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay precios guardados" in i.value for i in at.info)


def test_switching_symbol_changes_displayed_price(tmp_path):
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()
    repo.save([_ticker(symbol="BTCUSDT", price=64439.56)])
    repo.save([_ticker(symbol="ETHUSDT", price=1869.88)])
    service = _service_for(db_path, symbols=("BTCUSDT", "ETHUSDT"))

    btc = _run(service, symbol="BTCUSDT")
    eth = _run(service, symbol="ETHUSDT")

    assert not btc.exception and not eth.exception
    assert "64,439.5600" in [m.value for m in btc.metric]
    assert "1,869.8800" in [m.value for m in eth.metric]


class TestResponsiveViewModes:
    def test_view_selector_appears_in_sidebar(self, tmp_path):
        db_path = _populated_db(tmp_path)
        at = _run(_service_for(db_path))

        assert not at.exception
        assert len(at.sidebar.selectbox) == 1
        assert at.sidebar.selectbox[0].label == "Vista"

    def test_page_loads_in_wide_mode(self, tmp_path):
        db_path = _populated_db(tmp_path, prices=(100.0, 64439.56))
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Amplia").run(timeout=30)

        assert not at.exception
        assert "64,439.5600" in [m.value for m in at.metric]

    def test_page_loads_in_automatic_mode(self, tmp_path):
        db_path = _populated_db(tmp_path)
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Automática").run(timeout=30)

        assert not at.exception

    def test_switching_view_mode_does_not_raise_exceptions(self, tmp_path):
        db_path = _populated_db(tmp_path)
        at = _run(_service_for(db_path))

        for mode in ["Amplia", "Compacta", "Automática", "Amplia"]:
            at.sidebar.selectbox[0].select(mode).run(timeout=30)
            assert not at.exception

    def test_compact_mode_does_not_lose_price_change_or_chart(self, tmp_path):
        db_path = _populated_db(tmp_path, prices=(100.0, 64439.56))
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Compacta").run(timeout=30)

        assert not at.exception
        metric_values = [m.value for m in at.metric]
        assert "64,439.5600" in metric_values  # precio
        assert "+64,339.56" in metric_values  # variación absoluta
        assert len(at.get("plotly_chart")) == 1  # gráfico sigue presente
