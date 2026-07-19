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


def test_load_settings_reads_credentials_from_env_file(tmp_path, monkeypatch):
    # Aseguramos que no haya credenciales previas de otras pruebas o del sistema.
    for var in ["BINANCE_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN"]:
        monkeypatch.delenv(var, raising=False)

    config_path = _write_yaml(tmp_path, _valid_yaml())
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BINANCE_API_KEY=clave_de_prueba\nOPENAI_API_KEY=otra_clave\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_path=env_path)

    assert settings.binance.api_key == "clave_de_prueba"
    assert settings.ai.openai_api_key == "otra_clave"
    assert settings.telegram.bot_token is None


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
