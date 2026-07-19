"""
Pruebas para el stub de src/signals/postgres_repository.py.

PostgresSignalRepository todavía no está implementado a propósito (ver
docstring del archivo): esta prueba solo confirma que cumple la interfaz
SignalRepository y que, si se usa antes de tiempo, falla de forma clara en
vez de silenciosa.
"""

from datetime import datetime, timezone

import pytest

from src.signals.base import SignalRepository
from src.signals.postgres_repository import PostgresSignalRepository
from src.models.signal_data import SignalSnapshot


def _snapshot() -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance",
        symbol="BTCUSDT",
        trend="Neutral",
        trend_strength="Weak",
        ema_signal="Neutral",
        macd_signal="Neutral",
        rsi_signal="Neutral",
        bollinger_signal="Inside Bands",
        trend_reason="Sin historial suficiente.",
        ema_reason="Sin historial suficiente.",
        macd_reason="Sin historial suficiente.",
        rsi_reason="Sin historial suficiente.",
        bollinger_reason="Sin historial suficiente.",
        trend_rule_strength=0.0,
        ema_rule_strength=0.0,
        macd_rule_strength=0.0,
        rsi_rule_strength=0.0,
        bollinger_rule_strength=0.0,
        score=50.0,
        confidence="Medium",
        signal_type="Neutral",
        generated_at=datetime.now(timezone.utc),
    )


def test_postgres_signal_repository_implements_interface():
    repo = PostgresSignalRepository(connection_url="postgresql://example")
    assert isinstance(repo, SignalRepository)


def test_postgres_signal_repository_methods_raise_not_implemented():
    repo = PostgresSignalRepository(connection_url="postgresql://example")

    with pytest.raises(NotImplementedError):
        repo.init()
    with pytest.raises(NotImplementedError):
        repo.save(_snapshot())
    with pytest.raises(NotImplementedError):
        repo.fetch_latest("Binance", "BTCUSDT")
    with pytest.raises(NotImplementedError):
        repo.fetch_history("Binance", "BTCUSDT")
