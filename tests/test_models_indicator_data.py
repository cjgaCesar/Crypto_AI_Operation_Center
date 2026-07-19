"""Pruebas para el modelo IndicatorSnapshot (src/models/indicator_data.py)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.indicator_data import IndicatorSnapshot


def test_valid_snapshot_is_created_correctly():
    snapshot = IndicatorSnapshot(
        exchange="Binance",
        symbol="BTCUSDT",
        sma=100.0,
        ema_fast=101.0,
        ema_medium=102.0,
        ema_slow=103.0,
        rsi=55.0,
        macd_line=1.0,
        macd_signal=0.8,
        macd_histogram=0.2,
        bollinger_upper=110.0,
        bollinger_middle=100.0,
        bollinger_lower=90.0,
        vwap=99.0,
        calculated_at=datetime.now(timezone.utc),
    )
    assert snapshot.exchange == "Binance"
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.sma == 100.0


def test_all_indicator_fields_default_to_none():
    """Mientras no haya suficiente historial, cada indicador debe poder
    quedar en None sin que el modelo lo rechace."""
    snapshot = IndicatorSnapshot(
        exchange="Binance",
        symbol="BTCUSDT",
        calculated_at=datetime.now(timezone.utc),
    )
    assert snapshot.sma is None
    assert snapshot.ema_fast is None
    assert snapshot.ema_medium is None
    assert snapshot.ema_slow is None
    assert snapshot.rsi is None
    assert snapshot.macd_line is None
    assert snapshot.macd_signal is None
    assert snapshot.macd_histogram is None
    assert snapshot.bollinger_upper is None
    assert snapshot.bollinger_middle is None
    assert snapshot.bollinger_lower is None
    assert snapshot.vwap is None


def test_snapshot_requires_exchange_symbol_and_calculated_at():
    with pytest.raises(ValidationError):
        IndicatorSnapshot(symbol="BTCUSDT", calculated_at=datetime.now(timezone.utc))


def test_snapshot_rejects_invalid_indicator_type():
    with pytest.raises(ValidationError):
        IndicatorSnapshot(
            exchange="Binance",
            symbol="BTCUSDT",
            sma="no-es-un-numero",
            calculated_at=datetime.now(timezone.utc),
        )
