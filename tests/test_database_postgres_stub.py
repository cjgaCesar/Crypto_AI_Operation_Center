"""
Pruebas para el stub de src/database/postgres_repository.py.

PostgresMarketDataRepository todavía no está implementado a propósito (ver
docstring del archivo): esta prueba solo confirma que cumple la interfaz
MarketDataRepository y que, si se usa antes de tiempo, falla de forma clara
en vez de silenciosa.
"""

import pytest

from src.database.base import MarketDataRepository
from src.database.postgres_repository import PostgresMarketDataRepository


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
