"""
Pruebas para el stub src/ai/postgres_repository.py (PostgresAIRepository).

No está implementado a propósito (ver docstring del archivo): estas
pruebas solo confirman que cumple la interfaz AIRepository y que, si se usa
antes de tiempo, falla de forma clara en vez de silenciosa. Mismo patrón
que tests/test_database_postgres_stub.py y tests/test_signals_postgres_stub.py.
"""

import pytest

from src.ai.postgres_repository import PostgresAIRepository
from src.ai.repository import AIRepository


def test_postgres_ai_repository_implements_interface():
    repo = PostgresAIRepository(connection_url="postgresql://example")
    assert isinstance(repo, AIRepository)


def test_postgres_ai_repository_methods_raise_not_implemented():
    repo = PostgresAIRepository(connection_url="postgresql://example")

    with pytest.raises(NotImplementedError):
        repo.init()
    with pytest.raises(NotImplementedError):
        repo.save(None)
    with pytest.raises(NotImplementedError):
        repo.fetch_latest("Binance", "BTCUSDT")
    with pytest.raises(NotImplementedError):
        repo.fetch_history("Binance", "BTCUSDT")
