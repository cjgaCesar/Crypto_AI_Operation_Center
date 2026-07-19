"""Pruebas para el modelo SignalSnapshot (src/models/signal_data.py)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel,
    ConfidenceLevel,
    EMALabel,
    MACDLabel,
    RSILabel,
    SignalType,
    TrendLabel,
    TrendStrength,
)


def _snapshot(**overrides) -> SignalSnapshot:
    data = {
        "exchange": "Binance",
        "symbol": "BTCUSDT",
        "trend": TrendLabel.STRONG_BULLISH,
        "trend_strength": TrendStrength.STRONG,
        "ema_signal": EMALabel.BULLISH,
        "macd_signal": MACDLabel.BULLISH_CROSS,
        "rsi_signal": RSILabel.OVERBOUGHT,
        "bollinger_signal": BollingerLabel.UPPER_BAND,
        "trend_reason": "EMA rápida +10.00% sobre la EMA lenta, con las 3 EMA alineadas al alza.",
        "ema_reason": "EMA rápida está +4.76% sobre la EMA media.",
        "macd_reason": "MACD (1.5000) por encima de su línea de señal (1.0000).",
        "rsi_reason": "RSI en 75.00, por encima del umbral de sobrecompra (70).",
        "bollinger_reason": "Precio (109.0000) cerca o sobre la banda superior (110.0000).",
        "trend_rule_strength": 1.0,
        "ema_rule_strength": 1.0,
        "macd_rule_strength": 0.2,
        "rsi_rule_strength": 0.1667,
        "bollinger_rule_strength": 0.5,
        "score": 83.25,
        "confidence": ConfidenceLevel.VERY_HIGH,
        "signal_type": SignalType.BULLISH,
        "generated_at": datetime.now(timezone.utc),
    }
    data.update(overrides)
    return SignalSnapshot(**data)


def test_valid_signal_is_created_correctly():
    signal = _snapshot()
    assert signal.exchange == "Binance"
    assert signal.symbol == "BTCUSDT"
    assert signal.score == 83.25
    assert signal.signal_type == SignalType.BULLISH


def test_signal_uses_enums_not_bare_strings_internally():
    signal = _snapshot()
    assert isinstance(signal.trend, TrendLabel)
    assert isinstance(signal.ema_signal, EMALabel)
    assert isinstance(signal.macd_signal, MACDLabel)
    assert isinstance(signal.rsi_signal, RSILabel)
    assert isinstance(signal.bollinger_signal, BollingerLabel)
    assert isinstance(signal.confidence, ConfidenceLevel)
    assert isinstance(signal.signal_type, SignalType)
    assert isinstance(signal.trend_strength, TrendStrength)


def test_signal_accepts_plain_strings_and_coerces_to_enums():
    """Al leer desde SQLite (texto plano), Pydantic debe reconstruir los
    Enums automáticamente a partir del string guardado."""
    signal = _snapshot(trend="Bullish", confidence="High", signal_type="Neutral")
    assert signal.trend == TrendLabel.BULLISH
    assert signal.confidence == ConfidenceLevel.HIGH
    assert signal.signal_type == SignalType.NEUTRAL


def test_signal_preserves_all_reasons():
    signal = _snapshot()
    assert signal.trend_reason
    assert signal.ema_reason
    assert signal.macd_reason
    assert signal.rsi_reason
    assert signal.bollinger_reason


def test_signal_preserves_all_individual_rule_strengths():
    signal = _snapshot()
    assert signal.trend_rule_strength == 1.0
    assert signal.ema_rule_strength == 1.0
    assert signal.macd_rule_strength == 0.2
    assert signal.rsi_rule_strength == pytest.approx(0.1667)
    assert signal.bollinger_rule_strength == 0.5


def test_signal_requires_all_fields():
    with pytest.raises(ValidationError):
        SignalSnapshot(exchange="Binance", symbol="BTCUSDT")


def test_signal_rejects_invalid_score_type():
    with pytest.raises(ValidationError):
        _snapshot(score="no-es-un-numero")


@pytest.mark.parametrize("score", [-1.0, 100.1, 200.0])
def test_signal_rejects_score_outside_valid_range(score):
    with pytest.raises(ValidationError):
        _snapshot(score=score)


@pytest.mark.parametrize("score", [0.0, 50.0, 100.0])
def test_signal_accepts_score_at_range_boundaries(score):
    signal = _snapshot(score=score)
    assert signal.score == score


@pytest.mark.parametrize(
    "field",
    ["trend_rule_strength", "ema_rule_strength", "macd_rule_strength",
     "rsi_rule_strength", "bollinger_rule_strength"],
)
@pytest.mark.parametrize("bad_value", [-0.01, 1.01, -5.0, 5.0])
def test_signal_rejects_rule_strength_outside_valid_range(field, bad_value):
    with pytest.raises(ValidationError):
        _snapshot(**{field: bad_value})


def test_signal_rejects_empty_exchange():
    with pytest.raises(ValidationError):
        _snapshot(exchange="")


def test_signal_rejects_empty_symbol():
    with pytest.raises(ValidationError):
        _snapshot(symbol="")


def test_signal_rejects_invalid_enum_value():
    with pytest.raises(ValidationError):
        _snapshot(trend="Sideways")
