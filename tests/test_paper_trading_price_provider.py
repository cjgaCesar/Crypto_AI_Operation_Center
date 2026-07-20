"""
Pruebas para src/paper_trading/price_provider.py (RepositoryMarketPriceProvider), Etapa 6.5.

Usa SQLiteMarketDataRepository real (Etapa 1) con tmp_path -- no una
base mockeada -- para confirmar que el adaptador realmente lee el
último MarketTicker persistido y lo convierte a Decimal sin pérdida.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.market_data import MarketTicker
from src.paper_trading.price_provider import RepositoryMarketPriceProvider


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ticker(exchange="Binance", symbol="BTCUSDT", price=50000.0, queried_at=None) -> MarketTicker:
    return MarketTicker(
        exchange=exchange, symbol=symbol, price=price, volume_24h=1000.0,
        price_change_percent_24h=0.5, queried_at=queried_at or _now(),
    )


def _provider(tmp_path) -> tuple[RepositoryMarketPriceProvider, SQLiteMarketDataRepository]:
    repository = SQLiteMarketDataRepository(str(tmp_path / "market.db"))
    repository.init()
    return RepositoryMarketPriceProvider(repository), repository


class TestGetCurrentPrice:
    def test_returns_the_latest_price(self, tmp_path):
        provider, repository = _provider(tmp_path)
        base = _now()
        repository.save([_ticker(price=100.0, queried_at=base)])
        repository.save([_ticker(price=110.0, queried_at=base + timedelta(minutes=5))])

        price = provider.get_current_price("Binance", "BTCUSDT")

        assert price == Decimal("110.0")

    def test_returns_a_decimal_instance(self, tmp_path):
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(price=50000.0)])

        price = provider.get_current_price("Binance", "BTCUSDT")

        assert isinstance(price, Decimal)

    def test_converts_float_via_str_not_directly(self, tmp_path):
        """Decimal(str(0.1)) == Decimal('0.1'); Decimal(0.1) sería
        Decimal('0.1000000000000000055511151231257827021181583404541015625')."""
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(price=0.1)])

        price = provider.get_current_price("Binance", "BTCUSDT")

        assert price == Decimal("0.1")
        assert price != Decimal(0.1)

    def test_missing_symbol_raises_value_error(self, tmp_path):
        provider, repository = _provider(tmp_path)

        with pytest.raises(ValueError):
            provider.get_current_price("Binance", "DOESNOTEXIST")

    def test_zero_price_raises_value_error(self, tmp_path):
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(price=0.0)])

        with pytest.raises(ValueError):
            provider.get_current_price("Binance", "BTCUSDT")

    def test_negative_price_raises_value_error(self, tmp_path):
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(price=-1.0)])

        with pytest.raises(ValueError):
            provider.get_current_price("Binance", "BTCUSDT")


class TestGetCurrentPrices:
    def test_returns_prices_for_multiple_symbols(self, tmp_path):
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(symbol="BTCUSDT", price=50000.0)])
        repository.save([_ticker(symbol="ETHUSDT", price=2000.0)])

        prices = provider.get_current_prices([("Binance", "BTCUSDT"), ("Binance", "ETHUSDT")])

        assert prices == {
            ("Binance", "BTCUSDT"): Decimal("50000.0"),
            ("Binance", "ETHUSDT"): Decimal("2000.0"),
        }

    def test_missing_symbol_within_multiple_raises(self, tmp_path):
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(symbol="BTCUSDT", price=50000.0)])

        with pytest.raises(ValueError):
            provider.get_current_prices([("Binance", "BTCUSDT"), ("Binance", "DOESNOTEXIST")])

    def test_empty_symbol_list_returns_empty_dict(self, tmp_path):
        provider, repository = _provider(tmp_path)

        assert provider.get_current_prices([]) == {}


class TestIsolation:
    def test_module_does_not_import_binance_or_requests(self):
        import src.paper_trading.price_provider as module
        source = open(module.__file__, encoding="utf-8").read()
        assert "binance" not in source.lower()
        assert "import requests" not in source

    def test_does_not_modify_market_data(self, tmp_path):
        provider, repository = _provider(tmp_path)
        repository.save([_ticker(price=50000.0)])
        before = repository.fetch_all()

        provider.get_current_price("Binance", "BTCUSDT")

        after = repository.fetch_all()
        assert before == after
