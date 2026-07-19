"""
Prueba de integración de la Etapa 4: MarketData -> Indicators -> Signals -> AI.

Conecta las piezas reales (BinanceExchangeClient, SQLiteMarketDataRepository,
SQLiteIndicatorRepository, IndicatorEngine, SQLiteSignalRepository,
SignalEngine, SQLiteAIRepository, DecisionEngine con DummyProvider) a
través de MarketDataService, IndicatorService, SignalService y AIService,
igual que hace main.py en cada ciclo, y confirma que:

1. market_data, market_indicators y market_signals se siguen llenando
   exactamente igual que en la Etapa 3 (la Etapa 4 no las modifica).
2. ai_recommendations se llena con recomendaciones derivadas de esas
   señales, una vez que hay una señal disponible.
3. La recomendación generada es consistente con el signal_type de la
   señal más reciente (DummyProvider es determinista).
4. Repetir el ciclo varias veces acumula historial de recomendaciones.

Se simula ("mockea") solo la llamada de red a Binance; todo lo demás (los
4 servicios, los 4 repositorios, el archivo SQLite) es el código real del
proyecto. No se usa ninguna API de IA real (DummyProvider, sin red).
"""

from unittest.mock import patch, MagicMock

from src.ai.decision_engine import DecisionEngine
from src.ai.prompt_builder import PromptBuilder, PromptVersion
from src.ai.providers.dummy_provider import DummyProvider
from src.ai.recommendation import RecommendationAction
from src.ai.service import AIService
from src.ai.sqlite_repository import SQLiteAIRepository
from src.market.binance import BinanceExchangeClient
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.signals.sqlite_repository import SQLiteSignalRepository
from src.services.indicator_engine import IndicatorEngine
from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.signals.engine import SignalEngine
from src.signals.enums import SignalType
from src.signals.service import SignalService
from src.utils.config import (
    BollingerRuleSettings,
    ConfidenceThresholds,
    EMARuleSettings,
    IndicatorSettings,
    RSIRuleSettings,
    ScoreThresholds,
    SignalRuleSettings,
    SignalSettings,
    SignalWeights,
    TrendRuleSettings,
)


def _fake_response(symbol, price):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "symbol": symbol,
        "lastPrice": str(price),
        "volume": "1000.0",
        "priceChangePercent": "0.5",
    }
    return response


@patch("src.market.binance.requests.get")
def test_full_pipeline_market_data_indicators_signals_ai(mock_get, tmp_path):
    prices = iter([100.0 + i for i in range(40)])  # tendencia alcista sostenida

    def side_effect(url, params, timeout):
        return _fake_response(params["symbol"], next(prices))

    mock_get.side_effect = side_effect

    db_path = str(tmp_path / "integration.db")
    exchange_client = BinanceExchangeClient(base_url="https://api.binance.com")

    market_repository = SQLiteMarketDataRepository(db_path)
    market_repository.init()

    indicator_repository = SQLiteIndicatorRepository(db_path)
    indicator_repository.init()

    signal_repository = SQLiteSignalRepository(db_path)
    signal_repository.init()

    ai_repository = SQLiteAIRepository(db_path)
    ai_repository.init()

    indicator_settings = IndicatorSettings(
        sma=3, ema_fast=2, ema_medium=3, ema_slow=4, rsi=3,
        macd_fast=2, macd_slow=4, macd_signal=2,
        bollinger_period=3, bollinger_stddev=2,
        atr=14, adx=14, vwap=True,
    )
    signal_settings = SignalSettings(
        score=ScoreThresholds(bullish=80, neutral=50, bearish=20),
        weights=SignalWeights(trend=35, ema=20, macd=20, rsi=15, bollinger=10),
        confidence=ConfidenceThresholds(very_high=90, high=80, medium=60, low=40),
        rules=SignalRuleSettings(
            trend=TrendRuleSettings(neutral_band_pct=0.1, strong_diff_pct=1.0),
            ema=EMARuleSettings(neutral_band_pct=0.1),
            rsi=RSIRuleSettings(oversold=30, overbought=70),
            bollinger=BollingerRuleSettings(proximity_pct=10.0),
        ),
    )

    symbols = ["BTCUSDT"]
    market_data_service = MarketDataService(exchange_client, market_repository, symbols)
    indicator_service = IndicatorService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        engine=IndicatorEngine(indicator_settings),
        exchange=exchange_client.exchange_name,
        symbols=symbols,
    )
    signal_service = SignalService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        signal_repository=signal_repository,
        engine=SignalEngine(signal_settings),
        exchange=exchange_client.exchange_name,
        symbols=symbols,
    )
    ai_service = AIService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        signal_repository=signal_repository,
        ai_repository=ai_repository,
        decision_engine=DecisionEngine(
            provider=DummyProvider(delay_seconds=0.0),
            prompt_builder=PromptBuilder(),
            system_prompt="Eres un analista de mercado de criptomonedas.",
        ),
        exchange=exchange_client.exchange_name,
        symbols=symbols,
    )

    # Ciclo 1: solo 1 lectura. Ni indicadores, ni señales, ni recomendación todavía.
    market_data_service.run_cycle()
    indicator_service.run_cycle()
    signal_service.run_cycle()
    ai_service.run_cycle()

    assert len(market_repository.fetch_all()) == 1
    assert indicator_repository.fetch_latest("Binance", "BTCUSDT") is None
    assert signal_repository.fetch_latest("Binance", "BTCUSDT") is None
    assert ai_repository.fetch_latest("Binance", "BTCUSDT") is None

    # 9 ciclos más (10 en total): suficiente historial para ema_slow=4 y
    # para que la tendencia alcista sostenida se refleje en las señales.
    for _ in range(9):
        market_data_service.run_cycle()
        indicator_service.run_cycle()
        signal_service.run_cycle()
        ai_service.run_cycle()

    # Las 3 tablas de las Etapas 1/1.5/2/3 se siguen llenando exactamente igual.
    assert len(market_repository.fetch_all()) == 10
    latest_indicators = indicator_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest_indicators is not None

    latest_signal = signal_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest_signal is not None
    assert latest_signal.score > 50.0

    # ai_recommendations: se generó una recomendación en cuanto hubo señal.
    latest_recommendation = ai_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest_recommendation is not None
    assert latest_recommendation.exchange == "Binance"
    assert latest_recommendation.symbol == "BTCUSDT"
    assert latest_recommendation.provider == "DummyProvider"
    assert latest_recommendation.model == "dummy-v1"
    assert 0.0 <= latest_recommendation.confidence <= 100.0
    assert latest_recommendation.reasoning
    assert latest_recommendation.summary
    assert len(latest_recommendation.advantages) >= 1
    assert len(latest_recommendation.risks) >= 1
    assert latest_recommendation.prompt_version == PromptVersion.V1
    assert latest_recommendation.processing_time_ms >= 0.0
    assert latest_recommendation.raw_response is None  # DummyProvider siempre devuelve None

    # DummyProvider es determinista: con signal_type Bullish, debe recomendar Buy.
    if latest_signal.signal_type == SignalType.BULLISH:
        assert latest_recommendation.recommendation == RecommendationAction.BUY

    recommendation_history = ai_repository.fetch_history("Binance", "BTCUSDT")
    assert len(recommendation_history) == 9  # el primer ciclo no generó señal todavía
