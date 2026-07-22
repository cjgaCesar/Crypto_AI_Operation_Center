"""Pruebas para src/utils/config.py (carga de config.yaml + .env)."""

from pathlib import Path

import pytest
import yaml

from src.utils.config import load_settings


def _write_yaml(tmp_path: Path, content: dict) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return config_path


def _valid_yaml() -> dict:
    return {
        "symbols": ["BTCUSDT"],
        "interval_minutes": 5,
        "alerts": {"price_change_percent_low": -5.0, "price_change_percent_high": 5.0},
        "database": {"engine": "sqlite", "sqlite_path": "data/crypto_data.db"},
        "logging": {"path": "logs/app.log", "level": "INFO"},
        "binance": {"base_url": "https://api.binance.com", "timeout_seconds": 10},
        "indicators": {
            "sma": 20,
            "ema_fast": 20,
            "ema_medium": 50,
            "ema_slow": 200,
            "rsi": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "bollinger_period": 20,
            "bollinger_stddev": 2,
            "atr": 14,
            "adx": 14,
            "vwap": True,
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
            "enabled": True,
            "provider": "dummy",
            "model": "dummy-v1",
            "temperature": 0.2,
            "max_tokens": 500,
            "system_prompt": "Eres un analista de mercado.",
            "dummy_delay": 0,
        },
        "paper_trading": {
            "enabled": False,
            "database_path": "data/crypto_data.db",
            "initial_capital": "10000",
            "currency": "USDT",
            "fee_rate": "0.001",
            "max_order_value": "1000",
            "max_position_value": "5000",
            "rules_version": "v1",
        },
    }


def test_load_settings_without_env_file(tmp_path):
    config_path = _write_yaml(tmp_path, _valid_yaml())
    env_path = tmp_path / ".env"  # No se crea a propósito.

    settings = load_settings(config_path=config_path, env_path=env_path)

    assert settings.symbols == ["BTCUSDT"]
    assert settings.interval_minutes == 5
    assert settings.database.engine == "sqlite"
    assert settings.binance.api_key is None
    assert settings.ai.openai_api_key is None
    assert settings.indicators.sma == 20
    assert settings.indicators.ema_slow == 200
    assert settings.indicators.vwap is True
    assert settings.signals.score.bullish == 80
    assert settings.signals.weights.trend == 35
    assert settings.signals.weights.bollinger == 10
    assert settings.signals.confidence.very_high == 90
    assert settings.signals.rules.rsi.oversold == 30
    assert settings.ai_engine.enabled is True
    assert settings.ai_engine.provider == "dummy"
    assert settings.ai_engine.model == "dummy-v1"
    assert settings.ai_engine.future_api_key is None


def test_load_settings_reads_credentials_from_env_file(tmp_path, monkeypatch):
    # Aseguramos que no haya credenciales previas de otras pruebas o del sistema.
    for var in ["BINANCE_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "AI_FUTURE_API_KEY"]:
        monkeypatch.delenv(var, raising=False)

    config_path = _write_yaml(tmp_path, _valid_yaml())
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BINANCE_API_KEY=clave_de_prueba\nOPENAI_API_KEY=otra_clave\nAI_FUTURE_API_KEY=futura_clave\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_path=env_path)

    assert settings.binance.api_key == "clave_de_prueba"
    assert settings.ai.openai_api_key == "otra_clave"
    assert settings.telegram.bot_token is None
    assert settings.ai_engine.future_api_key == "futura_clave"


def test_telegram_settings_default_timeout_when_env_unset(tmp_path, monkeypatch):
    for var in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_TIMEOUT_SECONDS"]:
        monkeypatch.delenv(var, raising=False)

    config_path = _write_yaml(tmp_path, _valid_yaml())
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")

    assert settings.telegram.bot_token is None
    assert settings.telegram.chat_id is None
    assert settings.telegram.timeout_seconds == 10.0


def test_telegram_settings_reads_all_fields_from_env(tmp_path, monkeypatch):
    config_path = _write_yaml(tmp_path, _valid_yaml())
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=token_de_prueba\nTELEGRAM_CHAT_ID=chat_de_prueba\nTELEGRAM_TIMEOUT_SECONDS=15.5\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_path=env_path)

    assert settings.telegram.bot_token == "token_de_prueba"
    assert settings.telegram.chat_id == "chat_de_prueba"
    assert settings.telegram.timeout_seconds == 15.5


def test_paper_trading_telegram_mirrors_top_level_telegram_settings(tmp_path, monkeypatch):
    """Etapa 6.12: `paper_trading.telegram` reutiliza la misma
    `TelegramSettings` que `settings.telegram` -- nunca un segundo
    sistema de credenciales."""
    config_path = _write_yaml(tmp_path, _valid_yaml())
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=token_de_prueba\nTELEGRAM_CHAT_ID=chat_de_prueba\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_path=env_path)

    assert settings.paper_trading.telegram == settings.telegram
    assert settings.paper_trading.telegram.bot_token == "token_de_prueba"
    assert settings.paper_trading.telegram.chat_id == "chat_de_prueba"


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(config_path=tmp_path / "no_existe.yaml", env_path=tmp_path / ".env")


def test_missing_required_key_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["binance"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_sqlite_engine_without_path_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["database"]["sqlite_path"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_indicators_section_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["indicators"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_indicator_field_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["indicators"]["rsi"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_negative_indicator_period_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["indicators"]["ema_slow"] = -1
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_vwap_type_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["indicators"]["vwap"] = "sí"
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_bollinger_stddev_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["indicators"]["bollinger_stddev"] = 0
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_signals_section_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["signals"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_signals_score_subsection_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["signals"]["score"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_signals_rule_subsection_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["signals"]["rules"]["bollinger"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_signals_score_type_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["signals"]["score"]["bullish"] = "alto"
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_signals_confidence_field_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["signals"]["confidence"]["very_high"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_signals_weights_section_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["signals"]["weights"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_signals_weight_field_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["signals"]["weights"]["macd"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_negative_signals_weight_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["signals"]["weights"]["rsi"] = -5
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_all_zero_signals_weights_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["signals"]["weights"] = {"trend": 0, "ema": 0, "macd": 0, "rsi": 0, "bollinger": 0}
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_signals_weight_type_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["signals"]["weights"]["trend"] = "alto"
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_ai_section_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["ai"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_missing_ai_field_raises(tmp_path):
    bad_config = _valid_yaml()
    del bad_config["ai"]["system_prompt"]
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_ai_provider_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["ai"]["provider"] = "gemini"
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_ai_enabled_type_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["ai"]["enabled"] = "si"
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_negative_ai_dummy_delay_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["ai"]["dummy_delay"] = -1
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_invalid_ai_max_tokens_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["ai"]["max_tokens"] = 0
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_negative_ai_temperature_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["ai"]["temperature"] = -0.1
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_ai_temperature_above_reasonable_range_raises(tmp_path):
    bad_config = _valid_yaml()
    bad_config["ai"]["temperature"] = 2.1
    config_path = _write_yaml(tmp_path, bad_config)

    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_ai_temperature_at_boundaries_is_accepted(tmp_path):
    for temperature in (0.0, 2.0):
        config = _valid_yaml()
        config["ai"]["temperature"] = temperature
        config_path = _write_yaml(tmp_path, config)

        settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
        assert settings.ai_engine.temperature == temperature


def test_weights_dont_need_to_sum_to_100(tmp_path):
    """El agregador normaliza por la suma total; los pesos no tienen que
    sumar exactamente 100."""
    config = _valid_yaml()
    config["signals"]["weights"] = {"trend": 3, "ema": 2, "macd": 2, "rsi": 2, "bollinger": 1}
    config_path = _write_yaml(tmp_path, config)

    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.signals.weights.trend == 3


# --- reconciliation_inspection (Etapa 6.9) ---------------------------------


def test_reconciliation_inspection_defaults_when_block_missing(tmp_path):
    """Config antigua (sin el bloque, Etapa 6.8 y anteriores) sigue
    cargando, con los defaults seguros documentados en §23.13."""
    config = _valid_yaml()
    assert "reconciliation_inspection" not in config["paper_trading"]
    config_path = _write_yaml(tmp_path, config)

    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    ri = settings.paper_trading.reconciliation_inspection
    assert ri.enabled is False
    assert ri.interval_minutes == 60
    assert ri.run_on_startup is False
    assert ri.deliver_alerts is True
    assert ri.max_alert_delivery_attempts == 3
    assert ri.history_limit == 100
    assert ri.pending_alert_batch_size == 100


def test_reconciliation_inspection_enabled_false_explicit(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"enabled": False}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.paper_trading.reconciliation_inspection.enabled is False


def test_reconciliation_inspection_run_on_startup_false_by_default(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"enabled": True}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.paper_trading.reconciliation_inspection.run_on_startup is False


def test_reconciliation_inspection_valid_interval_accepted(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"interval_minutes": 15}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.paper_trading.reconciliation_inspection.interval_minutes == 15


def test_reconciliation_inspection_interval_zero_rejected(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"interval_minutes": 0}
    config_path = _write_yaml(tmp_path, config)
    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_reconciliation_inspection_valid_attempts_accepted(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"max_alert_delivery_attempts": 5}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.paper_trading.reconciliation_inspection.max_alert_delivery_attempts == 5


def test_reconciliation_inspection_attempts_zero_rejected(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"max_alert_delivery_attempts": 0}
    config_path = _write_yaml(tmp_path, config)
    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_reconciliation_inspection_history_limit_validated(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"history_limit": 0}
    config_path = _write_yaml(tmp_path, config)
    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_reconciliation_inspection_batch_size_validated(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {"pending_alert_batch_size": 0}
    config_path = _write_yaml(tmp_path, config)
    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")


def test_reconciliation_inspection_full_block_accepted(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["reconciliation_inspection"] = {
        "enabled": True, "interval_minutes": 30, "run_on_startup": True, "deliver_alerts": False,
        "max_alert_delivery_attempts": 5, "history_limit": 50, "pending_alert_batch_size": 20,
    }
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    ri = settings.paper_trading.reconciliation_inspection
    assert ri.enabled is True
    assert ri.interval_minutes == 30
    assert ri.run_on_startup is True
    assert ri.deliver_alerts is False
    assert ri.max_alert_delivery_attempts == 5
    assert ri.history_limit == 50
    assert ri.pending_alert_batch_size == 20


def test_paper_trading_enabled_false_does_not_block_manual_inspection_semantics(tmp_path):
    """paper_trading.enabled y reconciliation_inspection.enabled son gates
    independientes (§23.13): confirmamos que ambos se cargan sin
    interferirse entre sí."""
    config = _valid_yaml()
    config["paper_trading"]["enabled"] = False
    config["paper_trading"]["reconciliation_inspection"] = {"enabled": False}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.paper_trading.enabled is False
    assert settings.paper_trading.reconciliation_inspection.enabled is False


def test_scheduler_gate_is_independent_field(tmp_path):
    """El scheduler se gatea únicamente por reconciliation_inspection.enabled,
    no por paper_trading.enabled -- ambos pueden variar independientemente."""
    config = _valid_yaml()
    config["paper_trading"]["enabled"] = True
    config["paper_trading"]["reconciliation_inspection"] = {"enabled": False}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    assert settings.paper_trading.enabled is True
    assert settings.paper_trading.reconciliation_inspection.enabled is False


# --- inspection_notifications (Etapa 6.10) ---------------------------------


def test_inspection_notifications_defaults_when_block_missing(tmp_path):
    """Config antigua (sin el bloque, Etapa 6.0-6.9) sigue cargando, con
    logging=True preservando exactamente el comportamiento previo (§24.9)."""
    config = _valid_yaml()
    assert "inspection_notifications" not in config["paper_trading"]
    config_path = _write_yaml(tmp_path, config)

    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    notifications = settings.paper_trading.inspection_notifications
    assert notifications.logging is True
    assert notifications.email is False
    assert notifications.slack is False
    assert notifications.telegram is False
    assert notifications.webhook is False


def test_inspection_notifications_full_block_accepted(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["inspection_notifications"] = {
        "logging": False, "email": True, "slack": True, "telegram": True, "webhook": True,
    }
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    notifications = settings.paper_trading.inspection_notifications
    assert notifications.logging is False
    assert notifications.email is True
    assert notifications.slack is True
    assert notifications.telegram is True
    assert notifications.webhook is True


def test_inspection_notifications_partial_block_uses_defaults_for_missing_fields(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["inspection_notifications"] = {"email": True}
    config_path = _write_yaml(tmp_path, config)
    settings = load_settings(config_path=config_path, env_path=tmp_path / ".env")
    notifications = settings.paper_trading.inspection_notifications
    assert notifications.logging is True
    assert notifications.email is True
    assert notifications.slack is False


def test_inspection_notifications_invalid_type_rejected(tmp_path):
    config = _valid_yaml()
    config["paper_trading"]["inspection_notifications"] = {"logging": "yes"}
    config_path = _write_yaml(tmp_path, config)
    with pytest.raises(ValueError):
        load_settings(config_path=config_path, env_path=tmp_path / ".env")
