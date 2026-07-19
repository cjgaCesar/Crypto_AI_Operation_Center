"""Pruebas para RSIRule (src/signals/rules/rsi_rule.py)."""

import pytest

from src.signals.enums import Direction, RSILabel
from src.signals.rule_result import RuleResult
from src.signals.rules.rsi_rule import RSIRule
from src.utils.config import RSIRuleSettings


def _rule(oversold=30, overbought=70) -> RSIRule:
    return RSIRule(RSIRuleSettings(oversold=oversold, overbought=overbought))


def test_returns_typed_rule_result_instance():
    rule = _rule()
    result = rule.evaluate(25.0)
    assert isinstance(result, RuleResult)
    assert isinstance(result.label, RSILabel)


def test_oversold_below_threshold():
    rule = _rule()
    result = rule.evaluate(25.0)
    assert result.direction == Direction.BEARISH
    assert result.label == RSILabel.OVERSOLD
    assert 0.0 < result.strength <= 1.0
    assert "RSI" in result.reason
    assert result.reason


def test_oversold_at_zero_has_max_strength():
    rule = _rule()
    result = rule.evaluate(0.0)
    assert result.strength == pytest.approx(1.0)


def test_oversold_at_exact_threshold_has_zero_strength():
    rule = _rule()
    result = rule.evaluate(30.0)
    assert result.direction == Direction.BEARISH
    assert result.strength == pytest.approx(0.0)


def test_overbought_above_threshold():
    rule = _rule()
    result = rule.evaluate(75.0)
    assert result.direction == Direction.BULLISH
    assert result.label == RSILabel.OVERBOUGHT


def test_overbought_at_100_has_max_strength():
    rule = _rule()
    result = rule.evaluate(100.0)
    assert result.strength == pytest.approx(1.0)


def test_neutral_in_middle_zone():
    rule = _rule()
    result = rule.evaluate(50.0)
    assert result.direction == Direction.NEUTRAL
    assert result.label == RSILabel.NEUTRAL
    assert result.strength == 0.0


def test_neutral_when_rsi_missing():
    rule = _rule()
    assert rule.evaluate(None).direction == Direction.NEUTRAL


def test_strength_is_always_within_valid_range():
    rule = _rule()
    for rsi in [-10.0, 0.0, 50.0, 100.0, 150.0]:
        result = rule.evaluate(rsi)
        assert 0.0 <= result.strength <= 1.0
