"""Pruebas para src/dashboard/theme.py (paleta y funciones de color puras)."""

from src.ai.recommendation import RiskLevel
from src.dashboard.theme import (
    COLOR_NEGATIVE,
    COLOR_NEUTRAL,
    COLOR_POSITIVE,
    COLOR_WARNING,
    get_change_color,
    get_risk_color,
    get_signal_color,
)
from src.signals.enums import SignalType


class TestGetSignalColor:
    def test_bullish_is_positive(self):
        assert get_signal_color(SignalType.BULLISH) == COLOR_POSITIVE

    def test_bearish_is_negative(self):
        assert get_signal_color(SignalType.BEARISH) == COLOR_NEGATIVE

    def test_neutral_is_neutral(self):
        assert get_signal_color(SignalType.NEUTRAL) == COLOR_NEUTRAL

    def test_none_returns_neutral(self):
        assert get_signal_color(None) == COLOR_NEUTRAL

    def test_unknown_value_returns_neutral(self):
        assert get_signal_color("no-es-un-signal-type") == COLOR_NEUTRAL


class TestGetRiskColor:
    def test_low_is_positive(self):
        assert get_risk_color(RiskLevel.LOW) == COLOR_POSITIVE

    def test_very_low_is_positive(self):
        assert get_risk_color(RiskLevel.VERY_LOW) == COLOR_POSITIVE

    def test_medium_is_warning(self):
        assert get_risk_color(RiskLevel.MEDIUM) == COLOR_WARNING

    def test_high_is_negative(self):
        assert get_risk_color(RiskLevel.HIGH) == COLOR_NEGATIVE

    def test_very_high_is_negative(self):
        assert get_risk_color(RiskLevel.VERY_HIGH) == COLOR_NEGATIVE

    def test_none_returns_neutral(self):
        assert get_risk_color(None) == COLOR_NEUTRAL

    def test_unknown_value_returns_neutral(self):
        assert get_risk_color("no-es-un-risk-level") == COLOR_NEUTRAL


class TestGetChangeColor:
    def test_positive_value_is_positive(self):
        assert get_change_color(1.5) == COLOR_POSITIVE

    def test_negative_value_is_negative(self):
        assert get_change_color(-1.5) == COLOR_NEGATIVE

    def test_zero_is_neutral(self):
        assert get_change_color(0.0) == COLOR_NEUTRAL

    def test_none_returns_neutral(self):
        assert get_change_color(None) == COLOR_NEUTRAL
