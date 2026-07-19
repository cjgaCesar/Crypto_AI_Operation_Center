"""Pruebas para src/dashboard/formatters.py (funciones puras)."""

from datetime import datetime, timezone

from src.dashboard.formatters import (
    NOT_AVAILABLE,
    format_enum,
    format_percent,
    format_price,
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
