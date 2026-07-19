"""
Sistema de configuración del proyecto.

Combina dos fuentes distintas, a propósito:

- config/config.yaml: valores de comportamiento (monedas, intervalo de
  consulta, límites de alerta, rutas de archivos). No contiene secretos y
  sí se puede subir a git.
- .env: credenciales y secretos (claves de API, tokens). Nunca se sube a
  git (ver .gitignore). Se basa en .env.example.

En esta etapa (1.5) ninguna credencial se usa todavía para conectarse a un
servicio real: los campos existen en Settings para que los módulos futuros
(IA, Telegram, múltiples exchanges) los reciban listos para usar, pero el
propio proyecto no realiza ninguna llamada autenticada.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class BinanceSettings:
    base_url: str
    timeout_seconds: int
    # Reservados para futuros endpoints privados de Binance. Hoy siempre None.
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


@dataclass(frozen=True)
class DatabaseSettings:
    engine: str  # "sqlite" hoy; "postgres" en una etapa futura.
    sqlite_path: str
    # Solo se usará cuando engine sea "postgres" (ver src/database/postgres_repository.py).
    postgres_url: Optional[str] = None


@dataclass(frozen=True)
class LoggingSettings:
    path: str
    level: str


@dataclass(frozen=True)
class AlertThresholds:
    price_change_percent_low: float
    price_change_percent_high: float


@dataclass(frozen=True)
class TelegramSettings:
    # Reservados para la futura integración con Telegram. Hoy siempre None.
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


@dataclass(frozen=True)
class AISettings:
    # Reservados para la futura integración de inteligencia artificial. Hoy siempre None.
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None


@dataclass(frozen=True)
class ExternalDataSettings:
    # Reservados para futuras fuentes de datos adicionales. Hoy siempre None.
    coingecko_api_key: Optional[str] = None
    newsapi_api_key: Optional[str] = None


@dataclass(frozen=True)
class Settings:
    symbols: list[str]
    interval_minutes: float
    binance: BinanceSettings
    database: DatabaseSettings
    logging: LoggingSettings
    alerts: AlertThresholds
    telegram: TelegramSettings
    ai: AISettings
    external_data: ExternalDataSettings


def _load_yaml_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de configuración en: {config_path}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _validate_yaml_config(config)
    return config


def _validate_yaml_config(config: dict) -> None:
    required_keys = ["symbols", "interval_minutes", "database", "logging", "binance", "alerts"]
    missing = [key for key in required_keys if key not in config]
    if missing:
        raise ValueError(
            f"Faltan campos obligatorios en config.yaml: {', '.join(missing)}"
        )

    if not isinstance(config["symbols"], list) or not config["symbols"]:
        raise ValueError("El campo 'symbols' debe ser una lista con al menos una moneda.")

    if not isinstance(config["interval_minutes"], (int, float)) or config["interval_minutes"] <= 0:
        raise ValueError("El campo 'interval_minutes' debe ser un número mayor a 0.")

    db_cfg = config["database"]
    if "engine" not in db_cfg:
        raise ValueError("Falta 'database.engine' en config.yaml (ej. 'sqlite').")
    if db_cfg["engine"] == "sqlite" and "sqlite_path" not in db_cfg:
        raise ValueError("Falta 'database.sqlite_path' en config.yaml para el motor sqlite.")


def load_settings(
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
) -> Settings:
    """Carga la configuración combinando config.yaml (comportamiento) y .env (secretos).

    Si .env no existe todavía (caso normal en esta etapa, ya que solo se
    entrega .env.example), simplemente se omite y las credenciales quedan
    en None.
    """
    if env_path.exists():
        load_dotenv(env_path)

    config = _load_yaml_config(config_path)

    return Settings(
        symbols=config["symbols"],
        interval_minutes=config["interval_minutes"],
        binance=BinanceSettings(
            base_url=config["binance"]["base_url"],
            timeout_seconds=config["binance"]["timeout_seconds"],
            api_key=os.getenv("BINANCE_API_KEY") or None,
            api_secret=os.getenv("BINANCE_API_SECRET") or None,
        ),
        database=DatabaseSettings(
            engine=config["database"]["engine"],
            sqlite_path=config["database"].get("sqlite_path", "data/crypto_data.db"),
            postgres_url=os.getenv("DATABASE_URL") or None,
        ),
        logging=LoggingSettings(
            path=config["logging"]["path"],
            level=config["logging"]["level"],
        ),
        alerts=AlertThresholds(
            price_change_percent_low=config["alerts"]["price_change_percent_low"],
            price_change_percent_high=config["alerts"]["price_change_percent_high"],
        ),
        telegram=TelegramSettings(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        ),
        ai=AISettings(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        ),
        external_data=ExternalDataSettings(
            coingecko_api_key=os.getenv("COINGECKO_API_KEY") or None,
            newsapi_api_key=os.getenv("NEWSAPI_API_KEY") or None,
        ),
    )
