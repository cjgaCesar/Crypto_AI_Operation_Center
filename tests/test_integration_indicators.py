"""
Prueba de integración de la Etapa 2: mercado + indicadores.

Conecta las piezas reales (BinanceExchangeClient, SQLiteMarketDataRepository,
SQLiteIndicatorRepository, IndicatorEngine) a través de MarketDataService e
IndicatorService, igual que hace main.py en cada ciclo, y confirma que:

1. market_data sigue guardando únicamente datos crudos (no cambia por la
   Etapa 2).
2. market_indicators se llena con los indicadores calculados a partir de
   ese historial.
3. Repetir el ciclo varias veces (simulando el scheduler) va completando
   más indicadores a medida que se acumula historial.

Se simula ("mockea") solo la llamada de red a Binance; todo lo demás es el
código real del proyecto.
"""

from unittest.mock import patch, MagicMock

from src.market.binance import BinanceExchangeClient
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.services.indicator_engine import IndicatorEngine
from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.utils.config import IndicatorSettings


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
def test_market_and_indicator_services_work_together(mock_get, tmp_path):
    mock_get.side_effect = lambda url, params, timeout: _fake_response(params["symbol"], 100.0)

    db_path = str(tmp_path / "integration.db")
    exchange_client = BinanceExchangeClient(base_url="https://api.binance.com")

    market_repository = SQLiteMarketDataRepository(db_path)
    market_repository.init()

    indicator_repository = SQLiteIndicatorRepository(db_path)
    indicator_repository.init()

    # Periodos pequeños para que la prueba sea rápida y no dependa de
    # acumular cientos de ciclos como en producción (sma=20, ema_slow=200).
    small_settings = IndicatorSettings(
        sma=3, ema_fast=2, ema_medium=3, ema_slow=4, rsi=3,
        macd_fast=2, macd_slow=4, macd_signal=2,
        bollinger_period=3, bollinger_stddev=2,
        atr=14, adx=14, vwap=True,
    )

    symbols = ["BTCUSDT"]
    market_data_service = MarketDataService(exchange_client, market_repository, symbols)
    indicator_service = IndicatorService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        engine=IndicatorEngine(small_settings),
        exchange=exchange_client.exchange_name,
        symbols=symbols,
    )

    # Ciclo 1: con una sola lectura, el motor no puede calcular absolutamente
    # nada todavía (se requieren al menos 2), así que no se guarda snapshot.
    market_data_service.run_cycle()
    indicator_service.run_cycle()

    market_rows = market_repository.fetch_all()
    assert len(market_rows) == 1  # market_data solo tiene el dato crudo
    assert indicator_repository.fetch_latest("Binance", "BTCUSDT") is None

    # Ciclo 2: ya hay 2 lecturas; algunos indicadores de periodo corto
    # (ej. ema_fast=2) ya se pueden calcular, aunque otros (sma=3) todavía no.
    market_data_service.run_cycle()
    indicator_service.run_cycle()

    latest = indicator_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest is not None
    assert latest.ema_fast is not None
    assert latest.sma is None  # sma=3, todavía con solo 2 lecturas

    # Ciclos 3 y 4: se acumula suficiente historial para todos los indicadores.
    for _ in range(2):
        market_data_service.run_cycle()
        indicator_service.run_cycle()

    assert len(market_repository.fetch_all()) == 4  # market_data sigue creciendo

    latest = indicator_repository.fetch_latest("Binance", "BTCUSDT")
    assert latest.sma is not None
    assert latest.ema_slow is not None
    assert latest.rsi is not None

    history = indicator_repository.fetch_history("Binance", "BTCUSDT")
    # 3 snapshots: el primer ciclo no guardó nada (solo 1 lectura disponible).
    assert len(history) == 3
