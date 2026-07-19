"""Pruebas para src/dashboard/formatters.py (funciones puras)."""

from datetime import datetime, timedelta, timezone

from src.ai.recommendation import RiskLevel
from src.dashboard.formatters import (
    NOT_AVAILABLE,
    format_confidence,
    format_enum,
    format_percent,
    format_price,
    format_price_compact,
    format_relative_status,
    format_risk_level,
    format_score,
    format_timestamp,
)
from src.signals.enums import SignalType


class TestFormatPrice:
    def test_formats_with_default_decimals(self):
        assert format_price(64439.56) == "64,439.5600"

    def test_formats_with_custom_decimals(self):
        assert format_price(50.1, decimals=2) == "50.10"

    def test_none_returns_not_available(self):
        assert format_price(None) == NOT_AVAILABLE


class TestFormatPercent:
    def test_formats_positive_value_with_plus_sign(self):
        assert format_percent(1.234) == "+1.23%"

    def test_formats_negative_value_with_minus_sign(self):
        assert format_percent(-5.0) == "-5.00%"

    def test_none_returns_not_available(self):
        assert format_percent(None) == NOT_AVAILABLE


class TestFormatTimestamp:
    def test_formats_a_datetime(self):
        value = datetime(2026, 7, 19, 13, 43, 14, tzinfo=timezone.utc)
        assert format_timestamp(value) == "2026-07-19 13:43:14 UTC"

    def test_none_returns_not_available(self):
        assert format_timestamp(None) == NOT_AVAILABLE


class TestFormatEnum:
    def test_formats_enum_member_using_its_value(self):
        assert format_enum(SignalType.BULLISH) == "Bullish"

    def test_formats_plain_string_unchanged(self):
        assert format_enum("texto plano") == "texto plano"

    def test_none_returns_not_available(self):
        assert format_enum(None) == NOT_AVAILABLE


class TestFormatPriceCompact:
    def test_formats_with_default_two_decimals(self):
        assert format_price_compact(64439.56) == "64,439.56"

    def test_none_returns_not_available(self):
        assert format_price_compact(None) == NOT_AVAILABLE

    def test_does_not_mutate_original_value(self):
        value = 100.0
        format_price_compact(value)
        assert value == 100.0


class TestFormatConfidence:
    def test_formats_as_percentage_without_sign(self):
        assert format_confidence(60.0) == "60%"

    def test_formats_with_decimals_when_requested(self):
        assert format_confidence(59.5, decimals=1) == "59.5%"

    def test_none_returns_not_available(self):
        assert format_confidence(None) == NOT_AVAILABLE


class TestFormatScore:
    def test_formats_with_two_decimals(self):
        assert format_score(57.912646) == "57.91"

    def test_none_returns_not_available(self):
        assert format_score(None) == NOT_AVAILABLE


class TestFormatRiskLevel:
    def test_formats_enum_using_its_value(self):
        assert format_risk_level(RiskLevel.LOW) == "Low"

    def test_none_returns_not_available(self):
        assert format_risk_level(None) == NOT_AVAILABLE


class TestFormatRelativeStatus:
    def test_minutes_ago(self):
        reference = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        timestamp = reference - timedelta(minutes=5)
        assert format_relative_status(timestamp, reference=reference) == "Hace 5 min"

    def test_hours_ago(self):
        reference = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        timestamp = reference - timedelta(hours=3)
        assert format_relative_status(timestamp, reference=reference) == "Hace 3 h"

    def test_days_ago(self):
        reference = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
        timestamp = reference - timedelta(days=2)
        assert format_relative_status(timestamp, reference=reference) == "Hace 2 d"

    def test_just_now(self):
        reference = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        timestamp = reference - timedelta(seconds=10)
        assert format_relative_status(timestamp, reference=reference) == "Hace instantes"

    def test_none_returns_not_available(self):
        assert format_relative_status(None) == NOT_AVAILABLE
