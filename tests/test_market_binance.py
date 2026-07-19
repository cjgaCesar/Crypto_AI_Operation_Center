"""
Pruebas para src/market/binance.py.

No se hacen llamadas reales a internet en estas pruebas: se simula
("mockea") la respuesta de Binance para poder probar la lógica del cliente
de forma rápida y confiable, sin depender de la red.
"""

from unittest.mock import patch, MagicMock

import pytest
import requests

from src.market.binance import BinanceExchangeClient, BinanceClientError
from src.models.market_data import MarketTicker


def _fake_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


@patch("src.market.binance.requests.get")
def test_get_ticker_24hr_returns_market_ticker(mock_get):
    mock_get.return_value = _fake_response({
        "symbol": "BTCUSDT",
        "lastPrice": "64822.25",
        "volume": "8552.12",
        "priceChangePercent": "1.33",
    })

    client = BinanceExchangeClient(base_url="https://api.binance.com")
    result = client.get_ticker_24hr("BTCUSDT")

    assert isinstance(result, MarketTicker)
    assert result.exchange == "Binance"
    assert result.symbol == "BTCUSDT"
    assert result.price == 64822.25
    assert result.volume_24h == 8552.12
    assert result.price_change_percent_24h == 1.33


@patch("src.market.binance.requests.get")
def test_get_ticker_24hr_network_error_raises(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("sin conexión")

    client = BinanceExchangeClient(base_url="https://api.binance.com")
    with pytest.raises(BinanceClientError):
        client.get_ticker_24hr("BTCUSDT")


@patch("src.market.binance.requests.get")
def test_get_ticker_24hr_bad_response_raises(mock_get):
    # Falta el campo 'lastPrice', simulando una respuesta inesperada.
    mock_get.return_value = _fake_response({"symbol": "BTCUSDT"})

    client = BinanceExchangeClient(base_url="https://api.binance.com")
    with pytest.raises(BinanceClientError):
        client.get_ticker_24hr("BTCUSDT")


@patch("src.market.binance.requests.get")
def test_get_tickers_skips_failed_symbols(mock_get):
    def side_effect(url, params, timeout):
        if params["symbol"] == "BTCUSDT":
            return _fake_response({
                "symbol": "BTCUSDT",
                "lastPrice": "64822.25",
                "volume": "8552.12",
                "priceChangePercent": "1.33",
            })
        raise requests.exceptions.ConnectionError("sin conexión")

    mock_get.side_effect = side_effect

    client = BinanceExchangeClient(base_url="https://api.binance.com")
    results = client.get_tickers(["BTCUSDT", "ETHUSDT"])

    assert len(results) == 1
    assert results[0].symbol == "BTCUSDT"
    assert results[0].exchange == "Binance"
