"""Pruebas para BollingerRule (src/signals/rules/bollinger_rule.py)."""

import pytest

from src.signals.enums import BollingerLabel, Direction
from src.signals.rule_result import RuleResult
from src.signals.rules.bollinger_rule import BollingerRule
from src.utils.config import BollingerRuleSettings


def _rule(proximity_pct=10.0) -> BollingerRule:
    return BollingerRule(BollingerRuleSettings(proximity_pct=proximity_pct))


def test_returns_typed_rule_result_instance():
    rule = _rule()
    result = rule.evaluate(price=109.0, bollinger_upper=110.0, bollinger_lower=90.0)
    assert isinstance(result, RuleResult)
    assert isinstance(result.label, BollingerLabel)


def test_upper_band_when_price_near_upper():
    rule = _rule(proximity_pct=10.0)
    # Banda de 90 a 110 (ancho 20); 10% de proximidad = 2 -> "cerca" es >= 108.
    result = rule.evaluate(price=109.0, bollinger_upper=110.0, bollinger_lower=90.0)
    assert result.direction == Direction.BULLISH
    assert result.label == BollingerLabel.UPPER_BAND
    assert 0.0 < result.strength <= 1.0
    assert "Precio" in result.reason
    assert result.reason


def test_upper_band_at_the_band_has_max_strength():
    rule = _rule(proximity_pct=10.0)
    result = rule.evaluate(price=110.0, bollinger_upper=110.0, bollinger_lower=90.0)
    assert result.strength == pytest.approx(1.0)


def test_lower_band_when_price_near_lower():
    rule = _rule(proximity_pct=10.0)
    result = rule.evaluate(price=91.0, bollinger_upper=110.0, bollinger_lower=90.0)
    assert result.direction == Direction.BEARISH
    assert result.label == BollingerLabel.LOWER_BAND


def test_inside_bands_when_price_in_the_middle():
    rule = _rule(proximity_pct=10.0)
    result = rule.evaluate(price=100.0, bollinger_upper=110.0, bollinger_lower=90.0)
    assert result.direction == Direction.NEUTRAL
    assert result.label == BollingerLabel.INSIDE_BANDS
    assert result.strength == 0.0


def test_inside_bands_when_data_missing():
    rule = _rule()
    assert rule.evaluate(None, 110.0, 90.0).direction == Direction.NEUTRAL
    assert rule.evaluate(100.0, None, 90.0).direction == Direction.NEUTRAL
    assert rule.evaluate(100.0, 110.0, None).direction == Direction.NEUTRAL


def test_inside_bands_when_bands_are_invalid():
    rule = _rule()
    # upper <= lower no debería ocurrir en la práctica, pero se maneja sin error.
    result = rule.evaluate(100.0, 90.0, 110.0)
    assert result.direction == Direction.NEUTRAL
    assert result.label == BollingerLabel.INSIDE_BANDS


def test_strength_is_always_within_valid_range():
    rule = _rule()
    for price in [-1000.0, 90.0, 100.0, 110.0, 1000.0]:
        result = rule.evaluate(price, 110.0, 90.0)
        assert 0.0 <= result.strength <= 1.0
