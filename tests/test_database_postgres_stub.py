"""
Pruebas para los stubs de src/database/postgres_repository.py y
src/database/postgres_indicator_repository.py.

Ninguno de los dos está implementado a propósito (ver docstring de cada
archivo): estas pruebas solo confirman que cumplen su interfaz respectiva y
que, si se usan antes de tiempo, fallan de forma clara en vez de silenciosa.
"""

import pytest

from src.database.base import IndicatorRepository, MarketDataRepository
from src.database.postgres_repository import PostgresMarketDataRepository
from src.database.postgres_indicator_repository import PostgresIndicatorRepository


def test_postgres_repository_implements_interface():
    repo = PostgresMarketDataRepository(connection_url="postgresql://example")
    assert isinstance(repo, MarketDataRepository)


def test_postgres_repository_methods_raise_not_implemented():
    repo = PostgresMarketDataRepository(connection_url="postgresql://example")

    with pytest.raises(NotImplementedError):
        repo.init()
    with pytest.raises(NotImplementedError):
        repo.save([])
    with pytest.raises(NotImplementedError):
        repo.fetch_all()
    with pytest.raises(NotImplementedError):
        repo.fetch_by_symbol("Binance", "BTCUSDT")


def test_postgres_indicator_repository_implements_interface():
    repo = PostgresIndicatorRepository(connection_url="postgresql://example")
    assert isinstance(repo, IndicatorRepository)


def test_postgres_indicator_repository_methods_raise_not_implemented():
    repo = PostgresIndicatorRepository(connection_url="postgresql://example")

    with pytest.raises(NotImplementedError):
        repo.init()
    with pytest.raises(NotImplementedError):
        repo.save(None)
    with pytest.raises(NotImplementedError):
        repo.fetch_latest("Binance", "BTCUSDT")
    with pytest.raises(NotImplementedError):
        repo.fetch_history("Binance", "BTCUSDT")
