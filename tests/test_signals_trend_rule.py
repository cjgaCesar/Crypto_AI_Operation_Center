"""Pruebas para TrendRule (src/signals/rules/trend_rule.py)."""

import pytest

from src.signals.enums import Direction, TrendLabel
from src.signals.rule_result import RuleResult
from src.signals.rules.trend_rule import TrendRule
from src.utils.config import TrendRuleSettings


def _rule(neutral_band_pct=0.1, strong_diff_pct=1.0) -> TrendRule:
    return TrendRule(TrendRuleSettings(neutral_band_pct=neutral_band_pct, strong_diff_pct=strong_diff_pct))


def test_returns_typed_rule_result_instance():
    rule = _rule()
    result = rule.evaluate(ema_fast=110.0, ema_medium=105.0, ema_slow=100.0)
    assert isinstance(result, RuleResult)
    assert isinstance(result.label, TrendLabel)


def test_strong_bullish_when_emas_fully_aligned_and_diff_large():
    rule = _rule()
    result = rule.evaluate(ema_fast=110.0, ema_medium=105.0, ema_slow=100.0)
    assert result.direction == Direction.BULLISH
    assert result.label == TrendLabel.STRONG_BULLISH
    assert result.strength == pytest.approx(1.0)
    assert "EMA" in result.reason
    assert result.reason  # nunca vacío


def test_bullish_when_fast_above_slow_but_not_fully_aligned():
    rule = _rule()
    # ema_medium no queda entre fast y slow (fast > slow > medium): no está "alineado".
    result = rule.evaluate(ema_fast=102.0, ema_medium=99.0, ema_slow=100.0)
    assert result.direction == Direction.BULLISH
    assert result.label == TrendLabel.BULLISH
    assert 0.0 < result.strength <= 1.0


def test_strong_bearish_when_emas_fully_aligned_downwards():
    rule = _rule()
    result = rule.evaluate(ema_fast=90.0, ema_medium=95.0, ema_slow=100.0)
    assert result.direction == Direction.BEARISH
    assert result.label == TrendLabel.STRONG_BEARISH
    assert result.strength == pytest.approx(1.0)


def test_bearish_when_fast_below_slow_but_not_fully_aligned():
    rule = _rule()
    result = rule.evaluate(ema_fast=98.0, ema_medium=101.0, ema_slow=100.0)
    assert result.direction == Direction.BEARISH
    assert result.label == TrendLabel.BEARISH


def test_neutral_when_difference_within_band():
    rule = _rule(neutral_band_pct=0.5)
    result = rule.evaluate(ema_fast=100.1, ema_medium=100.0, ema_slow=100.0)
    assert result.direction == Direction.NEUTRAL
    assert result.label == TrendLabel.NEUTRAL
    assert result.strength == 0.0


def test_neutral_when_any_ema_missing():
    rule = _rule()
    for result in [
        rule.evaluate(None, 100.0, 100.0),
        rule.evaluate(100.0, None, 100.0),
        rule.evaluate(100.0, 100.0, None),
    ]:
        assert result.direction == Direction.NEUTRAL
        assert result.label == TrendLabel.NEUTRAL
        assert result.strength == 0.0
        assert result.reason  # nunca vacío


def test_neutral_when_ema_slow_is_zero():
    rule = _rule()
    result = rule.evaluate(100.0, 100.0, 0.0)
    assert result.direction == Direction.NEUTRAL


def test_strength_saturates_at_one_beyond_strong_threshold():
    rule = _rule(strong_diff_pct=1.0)
    # 20% de diferencia es mucho más que el umbral "fuerte" (1.0%): la
    # fuerza debe recortarse en 1.0, no seguir creciendo sin límite.
    result = rule.evaluate(ema_fast=120.0, ema_medium=110.0, ema_slow=100.0)
    assert result.strength == pytest.approx(1.0)


def test_strength_is_always_within_valid_range():
    """Pydantic ya garantiza 0<=strength<=1 en el propio RuleResult; esta
    prueba confirma que TrendRule nunca intenta producir un valor fuera de
    rango (lo cual haría fallar la construcción de RuleResult)."""
    rule = _rule()
    for fast, medium, slow in [(1000.0, 500.0, 100.0), (100.0, 100.0, 100.0), (1.0, 2.0, 3.0)]:
        result = rule.evaluate(fast, medium, slow)
        assert 0.0 <= result.strength <= 1.0
