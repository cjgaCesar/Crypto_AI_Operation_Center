"""Pruebas para src/dashboard/config.py."""

from pathlib import Path

import yaml

from src.dashboard.config import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    MAX_HISTORY_LIMIT,
    DashboardConfig,
    build_dashboard_config,
)
from src.utils.config import load_settings


def _valid_yaml() -> dict:
    return {
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "interval_minutes": 5,
        "alerts": {"price_change_percent_low": -5.0, "price_change_percent_high": 5.0},
        "database": {"engine": "sqlite", "sqlite_path": "data/test_dashboard.db"},
        "logging": {"path": "logs/app.log", "level": "INFO"},
        "binance": {"base_url": "https://api.binance.com", "timeout_seconds": 10},
        "indicators": {
            "sma": 20, "ema_fast": 20, "ema_medium": 50, "ema_slow": 200, "rsi": 14,
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "bollinger_period": 20, "bollinger_stddev": 2, "atr": 14, "adx": 14, "vwap": True,
        },
        "signals": {
            "score": {"bullish": 80, "neutral": 50, "bearish": 20},
            "weights": {"trend": 35, "ema": 20, "macd": 20, "rsi": 15, "bollinger": 10},
            "confidence": {"very_high": 90, "high": 80, "medium": 60, "low": 40},
            "rules": {
                "trend": {"neutral_band_pct": 0.1, "strong_diff_pct": 1.0},
                "ema": {"neutral_band_pct": 0.1},
                "rsi": {"oversold": 30, "overbought": 70},
                "bollinger": {"proximity_pct": 0.5},
            },
        },
        "ai": {
            "enabled": True, "provider": "dummy", "model": "dummy-v1",
            "temperature": 0.2, "max_tokens": 500,
            "system_prompt": "Eres un analista.", "dummy_delay": 0,
        },
    }


def _write_yaml(tmp_path: Path, content: dict) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return config_path


def test_build_dashboard_config_reads_database_path_and_symbols_from_settings(tmp_path):
    config_path = _write_yaml(tmp_path, _valid_yaml())
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    config = build_dashboard_config(settings, exchange="Binance")

    assert config.database_path == "data/test_dashboard.db"
    assert config.symbols == ["BTCUSDT", "ETHUSDT"]
    assert config.exchange == "Binance"


def test_build_dashboard_config_uses_internal_defaults(tmp_path):
    config_path = _write_yaml(tmp_path, _valid_yaml())
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    config = build_dashboard_config(settings, exchange="Binance")

    assert config.refresh_interval_seconds == DEFAULT_REFRESH_INTERVAL_SECONDS
    assert config.default_history_limit == DEFAULT_HISTORY_LIMIT
    assert config.max_history_limit == MAX_HISTORY_LIMIT


def test_default_values_match_the_documented_ones():
    assert DEFAULT_REFRESH_INTERVAL_SECONDS == 30
    assert DEFAULT_HISTORY_LIMIT == 100
    assert MAX_HISTORY_LIMIT == 1000


def test_dashboard_config_is_immutable():
    config = DashboardConfig(database_path="x.db", symbols=["BTCUSDT"], exchange="Binance")
    with_default_limits = (
        config.refresh_interval_seconds == 30
        and config.default_history_limit == 100
        and config.max_history_limit == 1000
    )
    assert with_default_limits
