"""
Pruebas para src/dashboard/pages/resumen.py, usando streamlit.testing.v1.AppTest
para ejecutar render() de verdad (no solo mocks) contra una base SQLite
temporal. No se prueban detalles frágiles de HTML/CSS: solo que la página
carga sin excepciones y que el contenido esperado (símbolos, precio,
señal, recomendación de IA, N/D) aparece.
"""

from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.ai.sqlite_repository import SQLiteAIRepository
from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)
from src.signals.sqlite_repository import SQLiteSignalRepository


def _ticker(symbol="BTCUSDT", price=100.0) -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol=symbol, price=price, volume_24h=1.0,
        price_change_percent_24h=1.5, queried_at=datetime.now(timezone.utc),
    )


def _signal(symbol="BTCUSDT") -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance", symbol=symbol,
        trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
        rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
        trend_reason="r", ema_reason="r", macd_reason="r", rsi_reason="r", bollinger_reason="r",
        trend_rule_strength=0.5, ema_rule_strength=0.5, macd_rule_strength=0.0,
        rsi_rule_strength=0.0, bollinger_rule_strength=0.0,
        score=70.0, confidence=ConfidenceLevel.MEDIUM, signal_type=SignalType.BULLISH,
        generated_at=datetime.now(timezone.utc),
    )


def _recommendation(symbol="BTCUSDT") -> AIRecommendation:
    return AIRecommendation(
        exchange="Binance", symbol=symbol, timestamp=datetime.now(timezone.utc),
        recommendation=RecommendationAction.BUY, confidence=60.0, risk_level=RiskLevel.MEDIUM,
        reasoning="r", advantages=["a"], risks=["b"], summary="s",
        provider="DummyProvider", model="dummy-v1", prompt_version="v1",
        processing_time_ms=1.0, raw_response=None,
    )


def _service_for(db_path: str, symbols=("BTCUSDT",)) -> DashboardService:
    repository = SQLiteDashboardRepository(db_path)
    return DashboardService(
        repository=repository, exchange="Binance", symbols=list(symbols),
        default_history_limit=100, max_history_limit=1000,
    )


def _render_resumen(service, exchange):
    from src.dashboard.pages import resumen
    resumen.render(service, exchange)


def _run(service, exchange="Binance", timeout=30):
    at = AppTest.from_function(_render_resumen, args=(service, exchange))
    at.run(timeout=timeout)
    return at


def test_page_loads_without_exceptions_against_populated_database(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()
    SQLiteMarketDataRepository(db_path).save([_ticker()])
    SQLiteSignalRepository(db_path).init()
    SQLiteSignalRepository(db_path).save(_signal())
    SQLiteAIRepository(db_path).init()
    SQLiteAIRepository(db_path).save(_recommendation())

    at = _run(_service_for(db_path))

    assert not at.exception


def test_page_shows_configured_symbols(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()

    at = _run(_service_for(db_path, symbols=("BTCUSDT", "ETHUSDT")))

    assert not at.exception
    all_text = " ".join(m.value for m in at.metric) + " ".join(md.value for md in at.markdown)
    assert "BTCUSDT" in all_text
    assert "ETHUSDT" in all_text


def test_page_shows_not_available_when_data_is_missing(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()

    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "N/D" in metric_values


def test_page_shows_price_when_market_data_exists(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()
    SQLiteMarketDataRepository(db_path).save([_ticker(price=64439.56)])

    at = _run(_service_for(db_path))

    metric_values = [m.value for m in at.metric]
    assert "64,439.56" in metric_values


def test_page_shows_signal_when_it_exists(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()
    SQLiteMarketDataRepository(db_path).save([_ticker()])
    SQLiteSignalRepository(db_path).init()
    SQLiteSignalRepository(db_path).save(_signal())

    at = _run(_service_for(db_path))

    all_markdown = " ".join(md.value for md in at.markdown)
    assert "Bullish" in all_markdown


def test_page_shows_ai_recommendation_when_it_exists(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()
    SQLiteMarketDataRepository(db_path).save([_ticker()])
    SQLiteSignalRepository(db_path).init()
    SQLiteSignalRepository(db_path).save(_signal())
    SQLiteAIRepository(db_path).init()
    SQLiteAIRepository(db_path).save(_recommendation())

    at = _run(_service_for(db_path))

    all_markdown = " ".join(md.value for md in at.markdown)
    assert "Buy" in all_markdown


def test_page_handles_missing_database(tmp_path):
    db_path = str(tmp_path / "does_not_exist.db")

    at = _run(_service_for(db_path))

    assert not at.exception
    assert any("todavía no existe" in i.value for i in at.info)


def test_page_handles_empty_symbols_list(tmp_path):
    db_path = str(tmp_path / "populated.db")
    SQLiteMarketDataRepository(db_path).init()

    at = _run(_service_for(db_path, symbols=()))

    assert not at.exception
    assert any("No hay símbolos configurados" in i.value for i in at.info)
