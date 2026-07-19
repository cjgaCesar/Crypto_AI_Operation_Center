"""
Pruebas para src/dashboard/pages/senales.py, usando
streamlit.testing.v1.AppTest para ejecutar render() de verdad (no solo
mocks) contra una base SQLite temporal. No se prueban detalles frágiles
de HTML/CSS: solo que la página carga sin excepciones y que el contenido
esperado (señal, score, confianza, tendencia, N/D, gráfico, tabla)
aparece.

El selector de símbolo en sí (compartido entre páginas) vive en
src/dashboard/app.py, no en senales.py: "cambio de símbolo" se valida
aquí llamando a render() con distintos símbolos, igual criterio que
tests/test_dashboard_market_page.py / test_dashboard_indicators_page.py.
"""

from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)
from src.signals.sqlite_repository import SQLiteSignalRepository
from src.models.signal_data import SignalSnapshot


def _signal(symbol="BTCUSDT", score=70.0, signal_type=SignalType.BULLISH) -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance", symbol=symbol,
        trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
        rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
        trend_reason="r", ema_reason="r", macd_reason="r", rsi_reason="r", bollinger_reason="r",
        trend_rule_strength=0.5, ema_rule_strength=0.5, macd_rule_strength=0.0,
        rsi_rule_strength=0.0, bollinger_rule_strength=0.0,
        score=score, confidence=ConfidenceLevel.MEDIUM, signal_type=signal_type,
        generated_at=datetime.now(timezone.utc),
    )


def _service_for(db_path: str, symbols=("BTCUSDT",)) -> DashboardService:
    repository = SQLiteDashboardRepository(db_path)
    return DashboardService(
        repository=repository, exchange="Binance", symbols=list(symbols),
        default_history_limit=100, max_history_limit=1000,
    )


def _render_senales(service, exchange, symbol, limit):
    from src.dashboard.pages import senales
    senales.render(service, exchange, symbol, limit)


def _run(service, exchange="Binance", symbol="BTCUSDT", limit=100, timeout=30):
    at = AppTest.from_function(_render_senales, args=(service, exchange, symbol, limit))
    at.run(timeout=timeout)
    return at


def _populated_db(tmp_path, snapshots=None) -> str:
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()
    for snapshot in snapshots or [_signal(score=65.0), _signal(score=70.0)]:
        repo.save(snapshot)
    return db_path


def test_page_loads_without_exceptions_against_populated_database(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception


def test_page_shows_current_signal(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal(signal_type=SignalType.BULLISH)])
    at = _run(_service_for(db_path))

    assert not at.exception
    all_markdown = " ".join(md.value for md in at.markdown)
    assert "Bullish" in all_markdown


def test_page_shows_score(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal(score=83.25)])
    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "83.25" in metric_values


def test_page_shows_confidence_and_trend(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal()])
    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "Medium" in metric_values
    assert "Bullish" in metric_values


def test_page_shows_component_signals(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal()])
    at = _run(_service_for(db_path))

    metric_labels = [m.label for m in at.metric]
    assert any("EMA" in lbl for lbl in metric_labels)
    assert any("MACD" in lbl for lbl in metric_labels)
    assert any("RSI" in lbl for lbl in metric_labels)
    assert any("Bollinger" in lbl for lbl in metric_labels)


def test_page_shows_generated_timestamp_and_record_count(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal(), _signal(), _signal()])
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "Generado" in caption_text
    assert "Registros disponibles: 3" in caption_text


def test_page_declares_risk_does_not_apply(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal()])
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "riesgo no aplica" in caption_text


def test_page_shows_score_history_chart(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.get("plotly_chart")) == 1


def test_page_shows_history_table(tmp_path):
    db_path = _populated_db(tmp_path, snapshots=[_signal(), _signal()])
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.dataframe) == 1


def test_page_shows_message_when_no_data(tmp_path):
    db_path = str(tmp_path / "empty.db")
    SQLiteSignalRepository(db_path).init()

    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay señales generadas" in i.value for i in at.info)
    assert len(at.get("plotly_chart")) == 0


def test_page_handles_missing_database(tmp_path):
    db_path = str(tmp_path / "does_not_exist.db")
    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay señales generadas" in i.value for i in at.info)


def test_switching_symbol_changes_displayed_signal(tmp_path):
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()
    repo.save(_signal(symbol="BTCUSDT", score=30.0, signal_type=SignalType.BEARISH))
    repo.save(_signal(symbol="ETHUSDT", score=90.0, signal_type=SignalType.BULLISH))
    service = _service_for(db_path, symbols=("BTCUSDT", "ETHUSDT"))

    btc = _run(service, symbol="BTCUSDT")
    eth = _run(service, symbol="ETHUSDT")

    assert not btc.exception and not eth.exception
    assert "30.00" in [m.value for m in btc.metric]
    assert "90.00" in [m.value for m in eth.metric]


class TestResponsiveViewModes:
    def test_view_selector_appears_in_sidebar(self, tmp_path):
        db_path = _populated_db(tmp_path)
        at = _run(_service_for(db_path))

        assert not at.exception
        assert len(at.sidebar.selectbox) == 1
        assert at.sidebar.selectbox[0].label == "Vista"

    def test_page_loads_in_wide_mode(self, tmp_path):
        db_path = _populated_db(tmp_path, snapshots=[_signal(score=65.0)])
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Amplia").run(timeout=30)

        assert not at.exception
        assert "65.00" in [m.value for m in at.metric]

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

    def test_compact_mode_does_not_lose_signal_score_or_history(self, tmp_path):
        db_path = _populated_db(tmp_path, snapshots=[_signal(score=65.0)])
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Compacta").run(timeout=30)

        assert not at.exception
        all_markdown = " ".join(md.value for md in at.markdown)
        assert "Bullish" in all_markdown  # señal
        assert "65.00" in [m.value for m in at.metric]  # score
        assert len(at.get("plotly_chart")) == 1  # gráfico de historial
        assert len(at.dataframe) == 1  # tabla de historial
