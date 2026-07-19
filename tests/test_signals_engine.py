"""Pruebas para SignalEngine (src/signals/engine.py)."""

from datetime import datetime, timezone

import pytest

from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot
from src.signals.engine import SignalEngine
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
from src.utils.config import (
    BollingerRuleSettings,
    ConfidenceThresholds,
    EMARuleSettings,
    RSIRuleSettings,
    ScoreThresholds,
    SignalRuleSettings,
    SignalSettings,
    SignalWeights,
    TrendRuleSettings,
)


def _settings() -> SignalSettings:
    return SignalSettings(
        score=ScoreThresholds(bullish=80, neutral=50, bearish=20),
        weights=SignalWeights(trend=35, ema=20, macd=20, rsi=15, bollinger=10),
        confidence=ConfidenceThresholds(very_high=90, high=80, medium=60, low=40),
        rules=SignalRuleSettings(
            trend=TrendRuleSettings(neutral_band_pct=0.1, strong_diff_pct=1.0),
            ema=EMARuleSettings(neutral_band_pct=0.1),
            rsi=RSIRuleSettings(oversold=30, overbought=70),
            bollinger=BollingerRuleSettings(proximity_pct=10.0),
        ),
    )


def _indicators(**overrides) -> IndicatorSnapshot:
    data = {
        "exchange": "Binance",
        "symbol": "BTCUSDT",
        "sma": 100.0,
        "ema_fast": 110.0,
        "ema_medium": 105.0,
        "ema_slow": 100.0,
        "rsi": 75.0,
        "macd_line": 1.5,
        "macd_signal": 1.0,
        "macd_histogram": 0.5,
        "bollinger_upper": 110.0,
        "bollinger_middle": 100.0,
        "bollinger_lower": 90.0,
        "vwap": 100.0,
        "calculated_at": datetime.now(timezone.utc),
    }
    data.update(overrides)
    return IndicatorSnapshot(**data)


def test_engine_returns_none_when_indicators_missing():
    engine = SignalEngine(_settings())
    assert engine.calculate("Binance", "BTCUSDT", None, price=100.0) is None


def test_engine_returns_none_when_price_missing():
    engine = SignalEngine(_settings())
    assert engine.calculate("Binance", "BTCUSDT", _indicators(), price=None) is None


def test_engine_produces_full_bullish_signal_with_typed_fields():
    engine = SignalEngine(_settings())
    indicators = _indicators()  # EMAs alineadas alcistas, RSI overbought, MACD bullish

    signal = engine.calculate("Binance", "BTCUSDT", indicators, price=109.0)

    assert isinstance(signal, SignalSnapshot)
    assert signal.exchange == "Binance"
    assert signal.symbol == "BTCUSDT"
    assert signal.trend == TrendLabel.STRONG_BULLISH
    assert signal.trend_strength == TrendStrength.STRONG
    assert signal.ema_signal == EMALabel.BULLISH
    assert signal.macd_signal == MACDLabel.BULLISH_CROSS
    assert signal.rsi_signal == RSILabel.OVERBOUGHT
    assert signal.bollinger_signal == BollingerLabel.UPPER_BAND  # precio 109 cerca de 110
    # Score ponderado (no todas las reglas están al 100% de fuerza con
    # estos valores): trend=1.0*35 + ema=1.0*20 + macd=0.2*20 + rsi=(5/30)*15
    # + bollinger=0.5*10, normalizado sobre pesos=100 -> 50 + 0.665*50 = 83.25.
    assert signal.score == pytest.approx(83.25)
    assert signal.confidence == ConfidenceLevel.VERY_HIGH  # las 5 reglas están de acuerdo
    assert signal.signal_type == SignalType.BULLISH

    # Las 5 razones deben venir pobladas (no vacías).
    assert signal.trend_reason
    assert signal.ema_reason
    assert signal.macd_reason
    assert signal.rsi_reason
    assert signal.bollinger_reason
    assert "EMA" in signal.trend_reason

    # Las 5 fuerzas individuales deben venir pobladas, cada una en [0,1].
    for strength in (
        signal.trend_rule_strength, signal.ema_rule_strength, signal.macd_rule_strength,
        signal.rsi_rule_strength, signal.bollinger_rule_strength,
    ):
        assert 0.0 <= strength <= 1.0
    assert signal.trend_rule_strength == pytest.approx(1.0)
    assert signal.macd_rule_strength == pytest.approx(0.2)


def test_engine_handles_missing_ema_slow_gracefully():
    """Si ema_slow todavía no está disponible (poco historial), el motor no
    debe fallar: TrendRule debe devolver Neutral, y el resto sigue evaluando."""
    engine = SignalEngine(_settings())
    indicators = _indicators(ema_slow=None)

    signal = engine.calculate("Binance", "BTCUSDT", indicators, price=100.0)

    assert signal is not None
    assert signal.trend == TrendLabel.NEUTRAL
    assert signal.trend_rule_strength == 0.0
    assert signal.rsi_signal == RSILabel.OVERBOUGHT  # no depende de ema_slow, sigue funcionando
    assert "todavía" in signal.trend_reason.lower() or "no hay" in signal.trend_reason.lower()
