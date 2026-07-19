"""
Pruebas para src/main.py (Composition Root): build_services() y
run_full_cycle().

Se simula ("mockea") solo la llamada de red a Binance; todo lo demás (los
4 servicios, los repositorios, el archivo SQLite) es el código real del
proyecto, exactamente como lo ejecuta 'python -m src.main'. El foco de
estas pruebas es el comportamiento de 'ai.enabled': cuando es False,
AIService no debe instanciarse ni ejecutarse, y las 3 etapas anteriores
deben seguir funcionando sin ningún error.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml

from src.ai.service import AIService
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.main import build_services, run_full_cycle
from src.signals.sqlite_repository import SQLiteSignalRepository
from src.utils.config import load_settings


def _base_config(sqlite_path: str, ai_enabled: bool) -> dict:
    return {
        "symbols": ["BTCUSDT"],
        "interval_minutes": 5,
        "alerts": {"price_change_percent_low": -5.0, "price_change_percent_high": 5.0},
        "database": {"engine": "sqlite", "sqlite_path": sqlite_path},
        "logging": {"path": "logs/app.log", "level": "INFO"},
        "binance": {"base_url": "https://api.binance.com", "timeout_seconds": 10},
        "indicators": {
            "sma": 3, "ema_fast": 2, "ema_medium": 3, "ema_slow": 4, "rsi": 3,
            "macd_fast": 2, "macd_slow": 4, "macd_signal": 2,
            "bollinger_period": 3, "bollinger_stddev": 2, "atr": 14, "adx": 14, "vwap": True,
        },
        "signals": {
            "score": {"bullish": 80, "neutral": 50, "bearish": 20},
            "weights": {"trend": 35, "ema": 20, "macd": 20, "rsi": 15, "bollinger": 10},
            "confidence": {"very_high": 90, "high": 80, "medium": 60, "low": 40},
            "rules": {
                "trend": {"neutral_band_pct": 0.1, "strong_diff_pct": 1.0},
                "ema": {"neutral_band_pct": 0.1},
                "rsi": {"oversold": 30, "overbought": 70},
                "bollinger": {"proximity_pct": 10.0},
            },
        },
        "ai": {
            "enabled": ai_enabled,
            "provider": "dummy",
            "model": "dummy-v1",
            "temperature": 0.2,
            "max_tokens": 500,
            "system_prompt": "Eres un analista de mercado.",
            "dummy_delay": 0,
        },
    }


def _write_config(tmp_path: Path, ai_enabled: bool, sqlite_path: str) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(_base_config(sqlite_path, ai_enabled)), encoding="utf-8")
    return config_path


def _fake_response(symbol, price):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "symbol": symbol, "lastPrice": str(price), "volume": "1000.0", "priceChangePercent": "0.5",
    }
    return response


@patch("src.market.binance.requests.get")
def test_build_services_instantiates_ai_service_when_enabled(mock_get, tmp_path):
    mock_get.side_effect = lambda url, params, timeout: _fake_response(params["symbol"], 100.0)

    db_path = str(tmp_path / "enabled.db")
    config_path = _write_config(tmp_path, ai_enabled=True, sqlite_path=db_path)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    _, _, _, ai_service = build_services(settings)

    assert ai_service is not None
    assert isinstance(ai_service, AIService)


@patch("src.market.binance.requests.get")
def test_build_services_does_not_instantiate_ai_service_when_disabled(mock_get, tmp_path):
    mock_get.side_effect = lambda url, params, timeout: _fake_response(params["symbol"], 100.0)

    db_path = str(tmp_path / "disabled.db")
    config_path = _write_config(tmp_path, ai_enabled=False, sqlite_path=db_path)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    _, _, _, ai_service = build_services(settings)

    assert ai_service is None


@patch("src.market.binance.requests.get")
def test_run_full_cycle_with_ai_disabled_runs_prior_stages_without_error(mock_get, tmp_path):
    prices = iter([100.0 + i for i in range(20)])
    mock_get.side_effect = lambda url, params, timeout: _fake_response(params["symbol"], next(prices))

    db_path = str(tmp_path / "disabled.db")
    config_path = _write_config(tmp_path, ai_enabled=False, sqlite_path=db_path)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    market_data_service, indicator_service, signal_service, ai_service = build_services(settings)
    assert ai_service is None

    # No debe lanzar ningún error al ejecutar varios ciclos con ai_service=None.
    for _ in range(6):
        run_full_cycle(market_data_service, indicator_service, signal_service, ai_service)

    market_repository = SQLiteMarketDataRepository(db_path)
    indicator_repository = SQLiteIndicatorRepository(db_path)
    signal_repository = SQLiteSignalRepository(db_path)

    # Etapas 1/1.5/2/3 siguen funcionando exactamente igual.
    assert len(market_repository.fetch_all()) == 6
    assert indicator_repository.fetch_latest("Binance", "BTCUSDT") is not None
    assert signal_repository.fetch_latest("Binance", "BTCUSDT") is not None

    # No se genera ninguna recomendación nueva: la tabla ni siquiera se creó.
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "ai_recommendations" not in tables


@patch("src.market.binance.requests.get")
def test_run_full_cycle_with_ai_enabled_generates_recommendations(mock_get, tmp_path):
    prices = iter([100.0 + i for i in range(20)])
    mock_get.side_effect = lambda url, params, timeout: _fake_response(params["symbol"], next(prices))

    db_path = str(tmp_path / "enabled.db")
    config_path = _write_config(tmp_path, ai_enabled=True, sqlite_path=db_path)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    market_data_service, indicator_service, signal_service, ai_service = build_services(settings)
    assert ai_service is not None

    for _ in range(6):
        run_full_cycle(market_data_service, indicator_service, signal_service, ai_service)

    from src.ai.sqlite_repository import SQLiteAIRepository
    ai_repository = SQLiteAIRepository(db_path)
    assert ai_repository.fetch_latest("Binance", "BTCUSDT") is not None
