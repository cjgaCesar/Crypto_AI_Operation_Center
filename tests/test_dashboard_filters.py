"""Pruebas para src/dashboard/filters.py (funciones puras, sin SQLite ni Streamlit)."""

import pytest

from src.dashboard.filters import normalize_exchange, normalize_symbol, validate_limit


class TestNormalizeSymbol:
    def test_uppercases_and_strips(self):
        assert normalize_symbol("  btcusdt  ") == "BTCUSDT"

    def test_already_normalized_symbol_unchanged(self):
        assert normalize_symbol("ETHUSDT") == "ETHUSDT"

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            normalize_symbol("")

    def test_rejects_whitespace_only_string(self):
        with pytest.raises(ValueError):
            normalize_symbol("   ")


class TestNormalizeExchange:
    def test_strips_whitespace(self):
        assert normalize_exchange("  Binance  ") == "Binance"

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            normalize_exchange("")

    def test_rejects_whitespace_only_string(self):
        with pytest.raises(ValueError):
            normalize_exchange("   ")


class TestValidateLimit:
    def test_returns_value_within_bounds_unchanged(self):
        assert validate_limit(50, default=100, maximum=1000) == 50

    def test_none_returns_default(self):
        assert validate_limit(None, default=100, maximum=1000) == 100

    def test_zero_returns_default(self):
        assert validate_limit(0, default=100, maximum=1000) == 100

    def test_negative_limit_returns_default(self):
        assert validate_limit(-5, default=100, maximum=1000) == 100

    def test_limit_above_maximum_is_clamped(self):
        assert validate_limit(5000, default=100, maximum=1000) == 1000

    def test_limit_exactly_at_maximum_is_accepted(self):
        assert validate_limit(1000, default=100, maximum=1000) == 1000

    def test_limit_of_one_is_accepted(self):
        assert validate_limit(1, default=100, maximum=1000) == 1
