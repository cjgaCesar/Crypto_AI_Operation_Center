"""
Prueba de integración: compatibilidad con el flujo de la Etapa 1.

Verifica que, conectando las piezas reales (BinanceExchangeClient +
SQLiteMarketDataRepository) a través de MarketDataService, el resultado final
es exactamente el mismo tipo de dato que se guardaba en la Etapa 1: por cada
símbolo consultado, un registro en SQLite con exchange, precio, volumen 24h,
variación % 24h y fecha/hora de consulta.

Se simula ("mockea") solo la llamada de red a Binance; todo lo demás
(servicio, repositorio, archivo SQLite) es el código real del proyecto.
"""

from unittest.mock import patch, MagicMock

from src.market.binance import BinanceExchangeClient
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.services.market_data_service import MarketDataService


def _fake_response(symbol, last_price, volume, change_pct):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "symbol": symbol,
        "lastPrice": last_price,
        "volume": volume,
        "priceChangePercent": change_pct,
    }
    return response


@patch("src.market.binance.requests.get")
def test_full_cycle_matches_stage_1_behavior(mock_get, tmp_path):
    fake_data = {
        "BTCUSDT": ("64822.25", "8552.12", "1.33"),
        "ETHUSDT": ("1871.88", "104392.19", "1.56"),
        "SOLUSDT": ("76.24", "795778.23", "1.24"),
    }

    def side_effect(url, params, timeout):
        symbol = params["symbol"]
        last_price, volume, change_pct = fake_data[symbol]
        return _fake_response(symbol, last_price, volume, change_pct)

    mock_get.side_effect = side_effect

    exchange_client = BinanceExchangeClient(base_url="https://api.binance.com", timeout_seconds=10)
    repository = SQLiteMarketDataRepository(str(tmp_path / "integration.db"))
    repository.init()

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    service = MarketDataService(exchange_client, repository, symbols)

    # Un ciclo completo, igual al que ejecuta main.py.
    service.run_cycle()

    stored = repository.fetch_all()

    assert len(stored) == 3
    assert [t.symbol for t in stored] == symbols

    btc = stored[0]
    assert btc.exchange == "Binance"
    assert btc.price == 64822.25
    assert btc.volume_24h == 8552.12
    assert btc.price_change_percent_24h == 1.33
    assert btc.queried_at is not None

    # El mismo servicio, ejecutado varias veces (como hace el scheduler cada
    # N minutos), debe seguir acumulando registros sin perder los anteriores.
    service.run_cycle()
    assert len(repository.fetch_all()) == 6
