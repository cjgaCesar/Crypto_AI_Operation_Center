"""
Pruebas para src/dashboard/pages/recomendaciones.py, usando
streamlit.testing.v1.AppTest para ejecutar render() de verdad (no solo
mocks) contra una base SQLite temporal. No se prueban detalles frágiles
de HTML/CSS: solo que la página carga sin excepciones y que el contenido
esperado (recomendación, confianza, riesgo, resumen, gráfico, tabla)
aparece.

El selector de símbolo en sí (compartido entre páginas) vive en
src/dashboard/app.py, no en recomendaciones.py: "cambio de símbolo" se
valida aquí llamando a render() con distintos símbolos, igual criterio
que los demás tests de página de esta serie.
"""

from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.ai.sqlite_repository import SQLiteAIRepository
from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService


def _recommendation(
    symbol="BTCUSDT", confidence=60.0, recommendation=RecommendationAction.BUY,
) -> AIRecommendation:
    return AIRecommendation(
        exchange="Binance", symbol=symbol, timestamp=datetime.now(timezone.utc),
        recommendation=recommendation, confidence=confidence, risk_level=RiskLevel.MEDIUM,
        reasoning="El motor de señales no muestra una inclinación clara.",
        advantages=["Alineado con el signal_type ya calculado."],
        risks=["DummyProvider es una simulación."],
        summary="Recomendación simulada.",
        provider="DummyProvider", model="dummy-v1", prompt_version="v1",
        processing_time_ms=1.0, raw_response=None,
    )


def _service_for(db_path: str, symbols=("BTCUSDT",)) -> DashboardService:
    repository = SQLiteDashboardRepository(db_path)
    return DashboardService(
        repository=repository, exchange="Binance", symbols=list(symbols),
        default_history_limit=100, max_history_limit=1000,
    )


def _render_recomendaciones(service, exchange, symbol, limit):
    from src.dashboard.pages import recomendaciones
    recomendaciones.render(service, exchange, symbol, limit)


def _run(service, exchange="Binance", symbol="BTCUSDT", limit=100, timeout=30):
    at = AppTest.from_function(_render_recomendaciones, args=(service, exchange, symbol, limit))
    at.run(timeout=timeout)
    return at


def _populated_db(tmp_path, recommendations=None) -> str:
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteAIRepository(db_path)
    repo.init()
    for recommendation in recommendations or [_recommendation(confidence=55.0), _recommendation(confidence=60.0)]:
        repo.save(recommendation)
    return db_path


def test_page_loads_without_exceptions_against_populated_database(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception


def test_page_shows_current_recommendation(tmp_path):
    db_path = _populated_db(tmp_path, recommendations=[_recommendation(recommendation=RecommendationAction.BUY)])
    at = _run(_service_for(db_path))

    assert not at.exception
    all_markdown = " ".join(md.value for md in at.markdown)
    assert "Buy" in all_markdown


def test_page_shows_confidence_and_risk(tmp_path):
    db_path = _populated_db(tmp_path, recommendations=[_recommendation(confidence=60.0)])
    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "60%" in metric_values
    all_markdown = " ".join(md.value for md in at.markdown)
    assert "Medium" in all_markdown


def test_page_shows_explanation(tmp_path):
    db_path = _populated_db(tmp_path, recommendations=[_recommendation()])
    at = _run(_service_for(db_path))

    # st.write() se registra como Markdown en AppTest.
    all_markdown = " ".join(md.value for md in at.markdown)
    assert "Recomendación simulada." in all_markdown


def test_page_shows_generated_timestamp_and_record_count(tmp_path):
    db_path = _populated_db(tmp_path, recommendations=[_recommendation(), _recommendation(), _recommendation()])
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "Generado" in caption_text
    assert "Registros disponibles: 3" in caption_text


def test_page_declares_simulated_provider(tmp_path):
    db_path = _populated_db(tmp_path, recommendations=[_recommendation()])
    at = _run(_service_for(db_path))

    caption_text = " ".join(c.value for c in at.caption)
    assert "DummyProvider" in caption_text
    assert "simulado" in caption_text


def test_page_shows_history_chart(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.get("plotly_chart")) == 1


def test_page_shows_history_table(tmp_path):
    db_path = _populated_db(tmp_path, recommendations=[_recommendation(), _recommendation()])
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.dataframe) == 1


def test_page_shows_message_when_no_data(tmp_path):
    db_path = str(tmp_path / "empty.db")
    SQLiteAIRepository(db_path).init()

    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay recomendaciones de IA" in i.value for i in at.info)
    assert len(at.get("plotly_chart")) == 0


def test_page_handles_missing_database(tmp_path):
    db_path = str(tmp_path / "does_not_exist.db")
    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("Todavía no hay recomendaciones de IA" in i.value for i in at.info)


def test_switching_symbol_changes_displayed_recommendation(tmp_path):
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteAIRepository(db_path)
    repo.init()
    repo.save(_recommendation(symbol="BTCUSDT", recommendation=RecommendationAction.SELL))
    repo.save(_recommendation(symbol="ETHUSDT", recommendation=RecommendationAction.STRONG_BUY))
    service = _service_for(db_path, symbols=("BTCUSDT", "ETHUSDT"))

    btc = _run(service, symbol="BTCUSDT")
    eth = _run(service, symbol="ETHUSDT")

    assert not btc.exception and not eth.exception
    assert "Sell" in " ".join(md.value for md in btc.markdown)
    assert "Strong Buy" in " ".join(md.value for md in eth.markdown)


class TestResponsiveViewModes:
    def test_view_selector_appears_in_sidebar(self, tmp_path):
        db_path = _populated_db(tmp_path)
        at = _run(_service_for(db_path))

        assert not at.exception
        assert len(at.sidebar.selectbox) == 1
        assert at.sidebar.selectbox[0].label == "Vista"

    def test_page_loads_in_wide_mode(self, tmp_path):
        db_path = _populated_db(tmp_path, recommendations=[_recommendation(confidence=65.0)])
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Amplia").run(timeout=30)

        assert not at.exception
        assert "65%" in [m.value for m in at.metric]

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

    def test_compact_mode_does_not_lose_recommendation_confidence_or_history(self, tmp_path):
        db_path = _populated_db(tmp_path, recommendations=[_recommendation(confidence=65.0)])
        at = _run(_service_for(db_path))

        at.sidebar.selectbox[0].select("Compacta").run(timeout=30)

        assert not at.exception
        all_markdown = " ".join(md.value for md in at.markdown)
        assert "Buy" in all_markdown  # recomendación
        assert "65%" in [m.value for m in at.metric]  # confianza
        assert len(at.get("plotly_chart")) == 1  # gráfico de historial
        assert len(at.dataframe) == 1  # tabla de historial
