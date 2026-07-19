"""
Prueba de integración de la Etapa 3: MarketData -> Indicators -> Signals.

Conecta las piezas reales (BinanceExchangeClient, SQLiteMarketDataRepository,
SQLiteIndicatorRepository, IndicatorEngine, SQLiteSignalRepository,
SignalEngine) a través de MarketDataService, IndicatorService y
SignalService, igual que hace main.py en cada ciclo, y confirma que:

1. market_data sigue guardando únicamente datos crudos (no cambia por la
   Etapa 3).
2. market_indicators se sigue llenando exactamente igual que en la Etapa 2.
3. market_signals se llena con señales derivadas de esos indicadores.
4. Repetir el ciclo varias veces (simulando el scheduler) acumula historial
   y termina generando una tendencia alcista clara, dado que los precios
   simulados suben de forma sostenida.

Se simula ("mockea") solo la llamada de red a Binance; todo lo demás
(los 3 servicios, los 3 repositorios, el archivo SQLite) es el código real
del proyecto.
"""

from unittest.mock import patch, MagicMock

from src.market.binance import BinanceExchangeClient
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.signals.sqlite_repository import SQLiteSignalRepository
from src.services.indicator_engine import IndicatorEngine
from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.signals.engine import SignalEngine
from src.signals.enums import SignalType, TrendLabel
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
def test_full_pipeline_market_data_indicators_signals(mock_get, tmp_path):
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

    # Ciclo 1: solo 1 lectura. Ni indicadores ni señales todavía.
    market_data_service.run_cycle()
    indicator_service.run_cycle()
    signal_service.run_cycle()

    assert len(market_repository.fetch_all()) == 1
    assert indicator_repository.fetch_latest("Binance", "BTCUSDT") is None
    assert signal_repository.fetch_latest("Binance", "BTCUSDT") is None

    # 9 ciclos más (10 en total): suficiente historial para ema_slow=4 y
    # para que la tendencia alcista sostenida se refleje en las señales.
    for _ in range(9):
        market_data_service.run_cycle()
        indicator_service.run_cycle()
        signal_service.run_cycle()

    # market_data: sigue guardando exactamente 1 registro crudo por ciclo.
    assert len(market_repository.fetch_all()) == 10

    # market_indicators: se generaron indicadores en cuanto hubo historial.
    latest_indicators = indicator_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest_indicators is not None
    assert latest_indicators.ema_slow is not None

    # market_signals: con precios subiendo de forma sostenida, la señal
    # final debe reflejar una tendencia alcista.
    latest_signal = signal_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest_signal is not None
    assert latest_signal.exchange == "Binance"
    assert latest_signal.symbol == "BTCUSDT"
    assert latest_signal.trend in (TrendLabel.BULLISH, TrendLabel.STRONG_BULLISH)
    assert latest_signal.score > 50.0
    assert latest_signal.signal_type in (SignalType.BULLISH, SignalType.NEUTRAL)
    assert latest_signal.trend_reason  # el detalle de cada regla debe quedar persistido
    assert latest_signal.ema_reason
    assert latest_signal.macd_reason
    assert latest_signal.rsi_reason
    assert latest_signal.bollinger_reason

    # La fuerza individual de cada regla también debe quedar persistida.
    for strength in (
        latest_signal.trend_rule_strength, latest_signal.ema_rule_strength,
        latest_signal.macd_rule_strength, latest_signal.rsi_rule_strength,
        latest_signal.bollinger_rule_strength,
    ):
        assert 0.0 <= strength <= 1.0

    signal_history = signal_repository.fetch_history("Binance", "BTCUSDT")
    assert len(signal_history) == 9  # el primer ciclo no generó señal (sin indicadores)
