"""Pruebas para MACDRule (src/signals/rules/macd_rule.py)."""

from src.signals.enums import Direction, MACDLabel
from src.signals.rule_result import RuleResult
from src.signals.rules.macd_rule import MACDRule


def test_returns_typed_rule_result_instance():
    rule = MACDRule()
    result = rule.evaluate(macd_line=1.5, macd_signal=1.0)
    assert isinstance(result, RuleResult)
    assert isinstance(result.label, MACDLabel)


def test_bullish_cross_when_line_above_signal():
    rule = MACDRule()
    result = rule.evaluate(macd_line=1.5, macd_signal=1.0)
    assert result.direction == Direction.BULLISH
    assert result.label == MACDLabel.BULLISH_CROSS
    assert 0.0 < result.strength <= 1.0
    assert "MACD" in result.reason
    assert result.reason


def test_bearish_cross_when_line_below_signal():
    rule = MACDRule()
    result = rule.evaluate(macd_line=0.5, macd_signal=1.0)
    assert result.direction == Direction.BEARISH
    assert result.label == MACDLabel.BEARISH_CROSS


def test_neutral_when_line_equals_signal():
    rule = MACDRule()
    result = rule.evaluate(macd_line=1.0, macd_signal=1.0)
    assert result.direction == Direction.NEUTRAL
    assert result.label == MACDLabel.NEUTRAL
    assert result.strength == 0.0


def test_neutral_when_values_missing():
    rule = MACDRule()
    assert rule.evaluate(None, 1.0).direction == Direction.NEUTRAL
    assert rule.evaluate(1.0, None).direction == Direction.NEUTRAL


def test_strength_reflects_relative_divergence():
    rule = MACDRule()
    small_gap = rule.evaluate(macd_line=1.05, macd_signal=1.0)
    large_gap = rule.evaluate(macd_line=10.0, macd_signal=1.0)
    assert large_gap.strength > small_gap.strength
    assert large_gap.strength <= 1.0


def test_strength_is_always_within_valid_range():
    rule = MACDRule()
    for line, signal in [(1000.0, -1000.0), (0.0001, 0.0001), (-5.0, 5.0)]:
        result = rule.evaluate(line, signal)
        assert 0.0 <= result.strength <= 1.0
