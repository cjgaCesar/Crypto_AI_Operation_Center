"""
Pruebas para el agregador de señales (src/signals/aggregator.py).

Cubren, por separado (para no mezclar los 4 conceptos que el agregador
documenta explícitamente):
- score: dirección × fuerza, ponderado por regla.
- confidence: acuerdo entre direcciones, incluyendo casos de empate.
- trend_strength: derivado solo de TrendRule.
- signal_type: clasificación del score final.
"""

import pytest

from src.signals.aggregator import aggregate
from src.signals.enums import (
    BollingerLabel,
    ConfidenceLevel,
    Direction,
    EMALabel,
    MACDLabel,
    RSILabel,
    SignalType,
    TrendLabel,
    TrendStrength,
)
from src.signals.rule_result import RuleResult
from src.utils.config import ConfidenceThresholds, ScoreThresholds, SignalWeights

SCORE_THRESHOLDS = ScoreThresholds(bullish=80, neutral=50, bearish=20)
CONFIDENCE = ConfidenceThresholds(very_high=90, high=80, medium=60, low=40)
EQUAL_WEIGHTS = SignalWeights(trend=1, ema=1, macd=1, rsi=1, bollinger=1)
DEFAULT_WEIGHTS = SignalWeights(trend=35, ema=20, macd=20, rsi=15, bollinger=10)


def _trend(direction: Direction, strength: float, label: TrendLabel) -> RuleResult[TrendLabel]:
    return RuleResult[TrendLabel](direction=direction, strength=strength, reason="r", label=label)


def _ema(direction: Direction, strength: float = 0.5) -> RuleResult[EMALabel]:
    label = {Direction.BULLISH: EMALabel.BULLISH, Direction.BEARISH: EMALabel.BEARISH}.get(
        direction, EMALabel.NEUTRAL
    )
    return RuleResult[EMALabel](direction=direction, strength=strength, reason="r", label=label)


def _macd(direction: Direction, strength: float = 0.5) -> RuleResult[MACDLabel]:
    label = {
        Direction.BULLISH: MACDLabel.BULLISH_CROSS, Direction.BEARISH: MACDLabel.BEARISH_CROSS,
    }.get(direction, MACDLabel.NEUTRAL)
    return RuleResult[MACDLabel](direction=direction, strength=strength, reason="r", label=label)


def _rsi(direction: Direction, strength: float = 0.5) -> RuleResult[RSILabel]:
    label = {Direction.BULLISH: RSILabel.OVERBOUGHT, Direction.BEARISH: RSILabel.OVERSOLD}.get(
        direction, RSILabel.NEUTRAL
    )
    return RuleResult[RSILabel](direction=direction, strength=strength, reason="r", label=label)


def _bollinger(direction: Direction, strength: float = 0.5) -> RuleResult[BollingerLabel]:
    label = {
        Direction.BULLISH: BollingerLabel.UPPER_BAND, Direction.BEARISH: BollingerLabel.LOWER_BAND,
    }.get(direction, BollingerLabel.INSIDE_BANDS)
    return RuleResult[BollingerLabel](direction=direction, strength=strength, reason="r", label=label)


def _aggregate(trend_dir, ema_dir, macd_dir, rsi_dir, bollinger_dir, strength=1.0, weights=EQUAL_WEIGHTS):
    trend_label = {
        Direction.BULLISH: TrendLabel.STRONG_BULLISH if strength >= 1.0 else TrendLabel.BULLISH,
        Direction.BEARISH: TrendLabel.STRONG_BEARISH if strength >= 1.0 else TrendLabel.BEARISH,
    }.get(trend_dir, TrendLabel.NEUTRAL)
    return aggregate(
        trend=_trend(trend_dir, strength if trend_dir != Direction.NEUTRAL else 0.0, trend_label),
        ema=_ema(ema_dir, strength if ema_dir != Direction.NEUTRAL else 0.0),
        macd=_macd(macd_dir, strength if macd_dir != Direction.NEUTRAL else 0.0),
        rsi=_rsi(rsi_dir, strength if rsi_dir != Direction.NEUTRAL else 0.0),
        bollinger=_bollinger(bollinger_dir, strength if bollinger_dir != Direction.NEUTRAL else 0.0),
        weights=weights,
        score_thresholds=SCORE_THRESHOLDS,
        confidence_thresholds=CONFIDENCE,
    )


# --- score (dirección × fuerza, ponderado) ---------------------------------

def test_all_rules_bullish_at_max_strength_gives_score_100():
    result = _aggregate(*(Direction.BULLISH,) * 5)
    assert result.score == pytest.approx(100.0)
    assert result.signal_type == SignalType.BULLISH


def test_all_rules_bearish_at_max_strength_gives_score_0():
    result = _aggregate(*(Direction.BEARISH,) * 5)
    assert result.score == pytest.approx(0.0)
    assert result.signal_type == SignalType.BEARISH


def test_all_rules_neutral_gives_score_50():
    result = _aggregate(*(Direction.NEUTRAL,) * 5)
    assert result.score == pytest.approx(50.0)
    assert result.signal_type == SignalType.NEUTRAL


def test_weights_change_the_score_for_the_same_rule_results():
    """Si trend pesa mucho más que las demás, un trend bajista debe pesar
    más en el score final que cuando todos los pesos son iguales."""
    heavy_trend_weights = SignalWeights(trend=90, ema=2.5, macd=2.5, rsi=2.5, bollinger=2.5)

    score_equal = _aggregate(
        Direction.BEARISH, Direction.BULLISH, Direction.BULLISH, Direction.BULLISH, Direction.BULLISH,
        weights=EQUAL_WEIGHTS,
    ).score
    score_heavy_trend = _aggregate(
        Direction.BEARISH, Direction.BULLISH, Direction.BULLISH, Direction.BULLISH, Direction.BULLISH,
        weights=heavy_trend_weights,
    ).score

    assert score_equal > 50.0
    assert score_heavy_trend < 50.0
    assert score_heavy_trend < score_equal


def test_weights_are_normalized_even_if_they_dont_sum_to_100():
    small_weights = SignalWeights(trend=3.5, ema=2.0, macd=2.0, rsi=1.5, bollinger=1.0)  # suma 10
    result = _aggregate(*(Direction.BULLISH,) * 5, weights=small_weights)
    assert result.score == pytest.approx(100.0)


def test_weights_dont_need_to_change_direction_of_score_thresholds():
    result = _aggregate(
        Direction.BULLISH, Direction.NEUTRAL, Direction.NEUTRAL, Direction.NEUTRAL, Direction.NEUTRAL,
        strength=0.2, weights=DEFAULT_WEIGHTS,
    )
    assert result.signal_type == SignalType.NEUTRAL


# --- trend_strength (solo de TrendRule) ------------------------------------

def test_trend_strength_is_strong_only_when_trend_label_is_strong():
    result = _aggregate(Direction.BULLISH, *(Direction.NEUTRAL,) * 4, strength=1.0)
    assert result.trend_strength == TrendStrength.STRONG


def test_trend_strength_is_medium_for_regular_bullish():
    result = _aggregate(Direction.BULLISH, *(Direction.NEUTRAL,) * 4, strength=0.3)
    assert result.trend_strength == TrendStrength.MEDIUM


def test_trend_strength_is_weak_when_trend_is_neutral():
    result = _aggregate(*(Direction.NEUTRAL,) * 5)
    assert result.trend_strength == TrendStrength.WEAK


# --- confidence: acuerdo entre direcciones, con casos de empate -----------

def test_confidence_five_rules_aligned_is_very_high():
    """Caso 1: las 5 reglas alineadas (100% de acuerdo)."""
    result = _aggregate(*(Direction.BULLISH,) * 5)
    assert result.confidence == ConfidenceLevel.VERY_HIGH


def test_confidence_four_aligned_and_one_neutral_is_high():
    """Caso 2: 4 reglas alineadas y 1 neutral (80% de acuerdo)."""
    result = _aggregate(
        Direction.BULLISH, Direction.BULLISH, Direction.BULLISH, Direction.BULLISH, Direction.NEUTRAL,
    )
    assert result.confidence == ConfidenceLevel.HIGH


def test_confidence_three_bullish_two_bearish_is_medium():
    """Caso 3: 3 alcistas y 2 bajistas (60% de acuerdo con la mayoría)."""
    result = _aggregate(
        Direction.BULLISH, Direction.BULLISH, Direction.BULLISH, Direction.BEARISH, Direction.BEARISH,
    )
    assert result.confidence == ConfidenceLevel.MEDIUM


def test_confidence_tie_between_directions_is_low():
    """Caso 4: empate — 2 alcistas, 2 bajistas, 1 neutral. El grupo más
    grande (empatado en 2) representa 40% -> Low. El resultado es el mismo
    sin importar cuál de los dos grupos empatados se calcule primero,
    porque confidence usa max() sobre los 3 conteos explícitos, no un
    "ganador" arbitrario del empate."""
    result = _aggregate(
        Direction.BULLISH, Direction.BULLISH, Direction.BEARISH, Direction.BEARISH, Direction.NEUTRAL,
    )
    assert result.confidence == ConfidenceLevel.LOW


def test_confidence_all_neutral_is_very_high():
    """Caso 5: las 5 reglas neutrales (100% de acuerdo, aunque sea en 'sin señal')."""
    result = _aggregate(*(Direction.NEUTRAL,) * 5)
    assert result.confidence == ConfidenceLevel.VERY_HIGH


def test_confidence_tie_result_is_deterministic_regardless_of_input_order():
    """El mismo empate (2 alcistas, 2 bajistas, 1 neutral), presentado en
    distinto orden de reglas, debe dar exactamente el mismo confidence."""
    order_a = _aggregate(
        Direction.BULLISH, Direction.BEARISH, Direction.BULLISH, Direction.BEARISH, Direction.NEUTRAL,
    )
    order_b = _aggregate(
        Direction.BEARISH, Direction.BEARISH, Direction.BULLISH, Direction.NEUTRAL, Direction.BULLISH,
    )
    assert order_a.confidence == order_b.confidence == ConfidenceLevel.LOW


def test_confidence_does_not_depend_on_weights_or_strength():
    """confidence mide solo el acuerdo en 'direction', no los pesos ni la
    fuerza: dos configuraciones con las mismas direcciones pero pesos y
    fuerzas distintas deben dar la misma confidence."""
    result_low_strength = _aggregate(*(Direction.BULLISH,) * 5, strength=0.1, weights=EQUAL_WEIGHTS)
    result_high_strength_diff_weights = _aggregate(
        *(Direction.BULLISH,) * 5, strength=1.0, weights=DEFAULT_WEIGHTS,
    )
    assert result_low_strength.confidence == result_high_strength_diff_weights.confidence
