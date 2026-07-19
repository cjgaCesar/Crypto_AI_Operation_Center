"""
Pruebas para src/dashboard/pages/indicadores.py, usando
streamlit.testing.v1.AppTest para ejecutar render() de verdad (no solo
mocks) contra una base SQLite temporal. No se prueban detalles frágiles
de HTML/CSS: solo que la página carga sin excepciones y que el contenido
esperado (RSI, MACD, medias móviles, N/D, gráficos) aparece.

El selector de símbolo en sí (compartido entre páginas) vive en
src/dashboard/app.py, no en indicadores.py: "cambio de símbolo" se
valida aquí llamando a render() con distintos símbolos, igual criterio
que tests/test_dashboard_market_page.py.
"""

from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.models.indicator_data import IndicatorSnapshot


def _indicators(symbol="BTCUSDT", rsi=50.0, sma=100.0) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        exchange="Binance", symbol=symbol, sma=sma, ema_fast=sma, ema_medium=sma,
        ema_slow=None, rsi=rsi, macd_line=0.1, macd_signal=0.05, macd_histogram=0.05,
        bollinger_upper=sma + 10, bollinger_middle=sma, bollinger_lower=sma - 10, vwap=sma,
        calculated_at=datetime.now(timezone.utc),
    )


def _service_for(db_path: str, symbols=("BTCUSDT",)) -> DashboardService:
    repository = SQLiteDashboardRepository(db_path)
    return DashboardService(
        repository=repository, exchange="Binance", symbols=list(symbols),
        default_history_limit=100, max_history_limit=1000,
    )


def _render_indicadores(service, exchange, symbol, limit):
    from src.dashboard.pages import indicadores
    indicadores.render(service, exchange, symbol, limit)


def _run(service, exchange="Binance", symbol="BTCUSDT", limit=100, timeout=30):
    at = AppTest.from_function(_render_indicadores, args=(service, exchange, symbol, limit))
    at.run(timeout=timeout)
    return at


def _populated_db(tmp_path, snapshots=None) -> str:
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()
    for snapshot in snapshots or [_indicators(rsi=45.0), _indicators(rsi=55.0)]:
        repo.save(snapshot)
    return db_path


def test_page_loads_without_exceptions_against_populated_database(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception


def test_page_shows_rsi_and_moving_averages(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_indicators(rsi=45.0, sma=64000.0)])
    at = _run(_service_for(db_path))

    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert "45.00" in metric_values
    assert "64,000.0000" in metric_values


def test_page_shows_macd_line_signal_and_histogram(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_indicators()])
    at = _run(_service_for(db_path))

    metric_labels = [m.label for m in at.metric]
    assert any("MACD" in lbl for lbl in metric_labels)
    assert any("Histograma" in lbl for lbl in metric_labels)


def test_page_shows_not_available_for_indicators_without_enough_history(tmp_path):
    """ema_slow siempre es None con tan poco historial (necesita 200
    lecturas) -- debe mostrarse 'N/D', nunca inventado."""
    db_path = _populated_db(tmp_path, snapshots=[_indicators()])
    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "N/D" in metric_values


def test_page_declares_atr_adx_and_volatility_as_not_available(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_indicators()])
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "ATR: N/D" in caption_text
    assert "ADX: N/D" in caption_text
    assert "Volatilidad: N/D" in caption_text


def test_page_shows_last_calculation_timestamp(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_indicators()])
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "Último cálculo" in caption_text


def test_page_shows_three_history_charts(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.get("plotly_chart")) == 3


def test_page_shows_message_when_no_data(tmp_path):
    db_path = str(tmp_path / "empty.db")
    SQLiteIndicatorRepository(db_path).init()

    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay indicadores calculados" in i.value for i in at.info)
    assert len(at.get("plotly_chart")) == 0


def test_page_handles_missing_database(tmp_path):
    db_path = str(tmp_path / "does_not_exist.db")
    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay indicadores calculados" in i.value for i in at.info)


def test_switching_symbol_changes_displayed_indicators(tmp_path):
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()
    repo.save(_indicators(symbol="BTCUSDT", rsi=30.0))
    repo.save(_indicators(symbol="ETHUSDT", rsi=70.0))
    service = _service_for(db_path, symbols=("BTCUSDT", "ETHUSDT"))

    btc = _run(service, symbol="BTCUSDT")
    eth = _run(service, symbol="ETHUSDT")

    assert not btc.exception and not eth.exception
    assert "30.00" in [m.value for m in btc.metric]
    assert "70.00" in [m.value for m in eth.metric]


class TestResponsiveViewModes:
    def test_view_selector_appears_in_sidebar(self, tmp_path):
        db_path = _populated_db(tmp_path)
        at = _run(_service_for(db_path))

        assert not at.exception
        assert len(at.sidebar.selectbox) == 1
        assert at.sidebar.selectbox[0].label == "Vista"

    def test_page_loads_in_wide_mode(self, tmp_path):
        db_path = _populated_db(tmp_path, snapshots=[_indicators(rsi=45.0)])
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Amplia").run(timeout=30)

        assert not at.exception
        assert "45.00" in [m.value for m in at.metric]

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

    def test_compact_mode_does_not_lose_indicators_or_charts(self, tmp_path):
        db_path = _populated_db(tmp_path, snapshots=[_indicators(rsi=45.0)])
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Compacta").run(timeout=30)

        assert not at.exception
        assert "45.00" in [m.value for m in at.metric]
        assert len(at.get("plotly_chart")) == 3
