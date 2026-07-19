"""
Pruebas para src/services/market_data_service.py.

Gracias a que el servicio depende de las interfaces ExchangeClient y
MarketDataRepository (y no de Binance/SQLite directamente), se pueden usar
implementaciones falsas ("fakes") en las pruebas, sin tocar red ni disco.
"""

from datetime import datetime, timezone

from src.database.base import MarketDataRepository
from src.market.base import ExchangeClient
from src.models.market_data import MarketTicker
from src.services.market_data_service import MarketDataService


class FakeExchangeClient(ExchangeClient):
    def __init__(self, tickers):
        self._tickers = tickers

    def get_tickers(self, symbols):
        return self._tickers


class FakeRepository(MarketDataRepository):
    def __init__(self):
        self.initialized = False
        self.saved = []

    def init(self):
        self.initialized = True

    def save(self, tickers):
        self.saved.extend(tickers)

    def fetch_all(self):
        return self.saved

    def fetch_by_symbol(self, exchange, symbol, limit=None):
        matches = [t for t in self.saved if t.exchange == exchange and t.symbol == symbol]
        return matches[-limit:] if limit is not None else matches


def _ticker(symbol="BTCUSDT") -> MarketTicker:
    return MarketTicker(
        exchange="Binance",
        symbol=symbol,
        price=1.0,
        volume_24h=1.0,
        price_change_percent_24h=1.0,
        queried_at=datetime.now(timezone.utc),
    )


def test_run_cycle_saves_tickers_from_exchange():
    tickers = [_ticker("BTCUSDT"), _ticker("ETHUSDT")]
    exchange_client = FakeExchangeClient(tickers)
    repository = FakeRepository()

    service = MarketDataService(exchange_client, repository, symbols=["BTCUSDT", "ETHUSDT"])
    service.run_cycle()

    assert repository.saved == tickers


def test_run_cycle_skips_save_when_no_tickers_returned():
    exchange_client = FakeExchangeClient([])
    repository = FakeRepository()

    service = MarketDataService(exchange_client, repository, symbols=["BTCUSDT"])
    service.run_cycle()

    assert repository.saved == []
