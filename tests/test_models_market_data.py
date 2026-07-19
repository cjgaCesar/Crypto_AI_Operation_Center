"""Pruebas para el modelo MarketTicker (src/models/market_data.py)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.market_data import MarketTicker


def test_valid_ticker_is_created_correctly():
    ticker = MarketTicker(
        symbol="BTCUSDT",
        price=64822.25,
        volume_24h=8552.12,
        price_change_percent_24h=1.33,
        queried_at=datetime.now(timezone.utc),
    )
    assert ticker.symbol == "BTCUSDT"
    assert ticker.price == 64822.25


def test_ticker_defaults_exchange_to_binance():
    """Hoy solo existe la implementación de Binance, así que si no se indica
    el exchange explícitamente, el valor por defecto debe ser 'Binance'."""
    ticker = MarketTicker(
        symbol="BTCUSDT",
        price=1.0,
        volume_24h=1.0,
        price_change_percent_24h=1.0,
        queried_at=datetime.now(timezone.utc),
    )
    assert ticker.exchange == "Binance"


def test_ticker_accepts_explicit_exchange():
    """Los exchanges futuros (Bybit, Coinbase, Kraken) deben poder indicar
    su propio nombre en vez de usar el valor por defecto."""
    ticker = MarketTicker(
        exchange="Bybit",
        symbol="BTCUSDT",
        price=1.0,
        volume_24h=1.0,
        price_change_percent_24h=1.0,
        queried_at=datetime.now(timezone.utc),
    )
    assert ticker.exchange == "Bybit"


def test_ticker_parses_iso_datetime_string():
    """El repositorio SQLite guarda fechas como texto ISO; el modelo debe
    poder reconstruirlas al leerlas de vuelta."""
    ticker = MarketTicker(
        symbol="BTCUSDT",
        price=1.0,
        volume_24h=1.0,
        price_change_percent_24h=1.0,
        queried_at="2026-07-19T02:48:12+00:00",
    )
    assert isinstance(ticker.queried_at, datetime)


def test_ticker_rejects_invalid_price():
    with pytest.raises(ValidationError):
        MarketTicker(
            symbol="BTCUSDT",
            price="no-es-un-numero",
            volume_24h=1.0,
            price_change_percent_24h=1.0,
            queried_at=datetime.now(timezone.utc),
        )


def test_ticker_requires_all_fields():
    with pytest.raises(ValidationError):
        MarketTicker(symbol="BTCUSDT")
