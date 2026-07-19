"""Pruebas para EMARule (src/signals/rules/ema_rule.py)."""

from src.signals.enums import Direction, EMALabel
from src.signals.rule_result import RuleResult
from src.signals.rules.ema_rule import EMARule
from src.utils.config import EMARuleSettings


def _rule(neutral_band_pct=0.1) -> EMARule:
    return EMARule(EMARuleSettings(neutral_band_pct=neutral_band_pct))


def test_returns_typed_rule_result_instance():
    rule = _rule()
    result = rule.evaluate(ema_fast=101.0, ema_medium=100.0)
    assert isinstance(result, RuleResult)
    assert isinstance(result.label, EMALabel)


def test_bullish_when_fast_clearly_above_medium():
    rule = _rule()
    result = rule.evaluate(ema_fast=101.0, ema_medium=100.0)
    assert result.direction == Direction.BULLISH
    assert result.label == EMALabel.BULLISH
    assert 0.0 < result.strength <= 1.0
    assert "EMA" in result.reason
    assert result.reason


def test_bearish_when_fast_clearly_below_medium():
    rule = _rule()
    result = rule.evaluate(ema_fast=99.0, ema_medium=100.0)
    assert result.direction == Direction.BEARISH
    assert result.label == EMALabel.BEARISH


def test_neutral_when_difference_within_band():
    rule = _rule(neutral_band_pct=1.0)
    result = rule.evaluate(ema_fast=100.5, ema_medium=100.0)
    assert result.direction == Direction.NEUTRAL
    assert result.label == EMALabel.NEUTRAL
    assert result.strength == 0.0


def test_neutral_when_values_missing():
    rule = _rule()
    assert rule.evaluate(None, 100.0).direction == Direction.NEUTRAL
    assert rule.evaluate(100.0, None).direction == Direction.NEUTRAL


def test_neutral_when_medium_is_zero():
    rule = _rule()
    assert rule.evaluate(100.0, 0.0).direction == Direction.NEUTRAL


def test_strength_increases_with_larger_divergence():
    rule = _rule(neutral_band_pct=0.1)
    small = rule.evaluate(ema_fast=100.2, ema_medium=100.0)
    large = rule.evaluate(ema_fast=110.0, ema_medium=100.0)
    assert large.strength > small.strength


def test_strength_is_always_within_valid_range():
    rule = _rule()
    for fast, medium in [(1000.0, 1.0), (1.0, 1.0), (-50.0, 100.0)]:
        result = rule.evaluate(fast, medium)
        assert 0.0 <= result.strength <= 1.0
