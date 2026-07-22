"""
Sistema de configuración del proyecto.

Combina dos fuentes distintas, a propósito:

- config/config.yaml: valores de comportamiento (monedas, intervalo de
  consulta, límites de alerta, rutas de archivos). No contiene secretos y
  sí se puede subir a git.
- .env: credenciales y secretos (claves de API, tokens). Nunca se sube a
  git (ver .gitignore). Se basa en .env.example.

Ninguna credencial se usa todavía para conectarse a un servicio real: los
campos existen en Settings para que los módulos futuros (IA, Telegram,
múltiples exchanges) los reciban listos para usar, pero el propio proyecto
no realiza ninguna llamada autenticada.

Desde la Etapa 2, Settings también incluye 'indicators' (IndicatorSettings),
con los periodos del motor de indicadores técnicos, igualmente configurables
desde config.yaml sin tocar código.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
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
    """Credenciales/configuración de Telegram, leídas desde `.env`.

    `bot_token`/`chat_id` quedan reservados en `None` a menos que se
    definan `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` en `.env` -- desde
    la Etapa 6.12, `paper_trading.inspection_notifications.telegram`
    (config.yaml) es lo que decide si el canal real de Paper Trading se
    activa; estas credenciales son obligatorias solo cuando ese flag es
    `true` (validado por `TelegramNotificationChannel`, ver
    src/paper_trading/notification_channels.py y
    docs/ARQUITECTURA_PAPER_TRADING.md §27), nunca por esta clase."""

    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class AISettings:
    """SOLO credenciales (secretos) para proveedores de IA reales, leídas
    desde variables de entorno (.env), nunca desde config.yaml.

    Distinta de 'AIEngineSettings' (más abajo), que configura el
    COMPORTAMIENTO del motor de IA de la Etapa 4 (qué proveedor usar, qué
    modelo, temperatura, etc.), leído desde config.yaml -> ai. Existen como
    dos clases separadas, sin fusionarse, para no romper
    'settings.ai.openai_api_key' ya usado en pruebas existentes desde la
    Etapa 1.5 (ver tests/test_utils_config.py) ni mezclar secretos con
    comportamiento configurable. Hoy ninguno de estos dos campos se usa
    para conectarse a un servicio real (Etapa 4 usa DummyProvider)."""

    # Reservados para la futura integración de inteligencia artificial. Hoy siempre None.
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None


@dataclass(frozen=True)
class ExternalDataSettings:
    # Reservados para futuras fuentes de datos adicionales. Hoy siempre None.
    coingecko_api_key: Optional[str] = None
    newsapi_api_key: Optional[str] = None


@dataclass(frozen=True)
class IndicatorSettings:
    """Periodos del motor de indicadores técnicos (Etapa 2).

    Todos se leen desde config.yaml -> indicators; para cambiar un periodo
    (ej. RSI de 14 a 21) solo hay que editar config.yaml, sin tocar código.

    'atr' y 'adx' existen para completar la configuración solicitada, pero
    el motor de indicadores (src/services/indicator_engine.py) todavía NO
    los calcula: ambos requieren datos de máximo/mínimo por vela (OHLC) que
    el endpoint de Binance usado hoy (ticker/24hr) no provee por intervalo.
    Ver docs/ARQUITECTURA.md.
    """

    sma: int
    ema_fast: int
    ema_medium: int
    ema_slow: int
    rsi: int
    macd_fast: int
    macd_slow: int
    macd_signal: int
    bollinger_period: int
    bollinger_stddev: float
    atr: int
    adx: int
    vwap: bool


@dataclass(frozen=True)
class ScoreThresholds:
    """Umbrales (0-100) para clasificar el SCORE FINAL ya ponderado en un
    SignalType (Bullish/Neutral/Bearish).

    Si score >= bullish -> SignalType.BULLISH; si score <= bearish ->
    SignalType.BEARISH; en cualquier otro caso -> SignalType.NEUTRAL.
    'neutral' se guarda como referencia informativa (punto medio esperado),
    pero no participa directamente en la clasificación (solo bullish y
    bearish son los límites que se comparan).
    """

    bullish: float
    neutral: float
    bearish: float


@dataclass(frozen=True)
class SignalWeights:
    """Peso (aporte relativo) de cada regla en el cálculo del score final.

    El agregador (src/signals/aggregator.py) combina el 'direction' y la
    'strength' de cada RuleResult, ponderados por estos 5 valores, en vez
    de promediarlos con el mismo peso. No es necesario que sumen 100
    exactamente: el agregador siempre normaliza por la suma total.
    """

    trend: float
    ema: float
    macd: float
    rsi: float
    bollinger: float


@dataclass(frozen=True)
class ConfidenceThresholds:
    """Umbrales (0-100) para clasificar el nivel de confianza de una señal.

    'very_high' no fue parte de los valores que se pidieron explícitamente
    (solo se dieron high/medium/low); se agregó para completar las 5
    categorías requeridas (Very Low/Low/Medium/High/Very High), como el
    punto medio entre 'high' y el máximo (100). Es completamente
    configurable, no está fijo en el código.
    """

    very_high: float
    high: float
    medium: float
    low: float


@dataclass(frozen=True)
class TrendRuleSettings:
    # % de diferencia entre ema_fast y ema_slow por debajo del cual se considera "Neutral".
    neutral_band_pct: float
    # % de diferencia a partir del cual, con las 3 EMA alineadas, se considera "Strong".
    strong_diff_pct: float


@dataclass(frozen=True)
class EMARuleSettings:
    # % de diferencia entre ema_fast y ema_medium por debajo del cual se considera "Neutral".
    neutral_band_pct: float


@dataclass(frozen=True)
class RSIRuleSettings:
    oversold: float
    overbought: float


@dataclass(frozen=True)
class BollingerRuleSettings:
    # % del ancho de la banda considerado "cerca" de la banda superior/inferior.
    proximity_pct: float


@dataclass(frozen=True)
class SignalRuleSettings:
    trend: TrendRuleSettings
    ema: EMARuleSettings
    rsi: RSIRuleSettings
    bollinger: BollingerRuleSettings


@dataclass(frozen=True)
class SignalSettings:
    """Configuración del motor de señales (Etapa 3).

    Todos los umbrales de todas las reglas son configurables desde
    config.yaml -> signals; ninguna regla tiene un valor fijo en el código.
    """

    score: ScoreThresholds
    weights: SignalWeights
    confidence: ConfidenceThresholds
    rules: SignalRuleSettings


@dataclass(frozen=True)
class AIEngineSettings:
    """Configuración del motor de IA (Etapa 4).

    Distinta de 'AISettings' (más arriba): 'AISettings' SOLO reserva las
    claves privadas de OpenAI/Anthropic leídas desde .env (secretos);
    'AIEngineSettings' configura el COMPORTAMIENTO del motor de IA
    (proveedor activo, modelo, parámetros de generación), leído desde
    config.yaml -> ai, igual que 'signals' o 'indicators'. Ninguna clave de
    API vive aquí -- para evitar nombres ambiguos: "credenciales" siempre
    está en 'Settings.ai'; "comportamiento del motor" siempre está en
    'Settings.ai_engine'.

    Nota: se evaluó fusionar ambas en una sola estructura (tal como sugiere
    la Etapa 4), pero se descartó porque 'settings.ai.openai_api_key' ya
    tiene pruebas dependientes desde la Etapa 1.5
    (tests/test_utils_config.py) y fusionar habría sido una modificación
    innecesaria de una funcionalidad ya aprobada, sin ningún beneficio
    técnico real (ambas clases ya están claramente separadas y
    documentadas).

    - 'enabled': si es False, AIService no ejecuta ningún ciclo (permite
      desactivar la Etapa 4 sin quitar código).
    - 'provider': qué AIProvider usar ("dummy", "openai" o "claude"). Hoy
      solo "dummy" está realmente conectado; "openai"/"claude" existen como
      estructura preparada (ver src/ai/providers/), sin conectar APIs reales.
    - 'model', 'temperature', 'max_tokens', 'system_prompt': parámetros que
      recibirán los proveedores reales cuando se conecten.
    - 'dummy_delay': segundos que DummyProvider espera antes de responder,
      para simular la latencia de un proveedor real en pruebas manuales.
    - 'future_api_key': reservado para un proveedor futuro que no sea
      OpenAI/Anthropic (que ya tienen su propio campo en AISettings); nunca
      se lee desde config.yaml (sería un secreto), sino desde la variable de
      entorno AI_FUTURE_API_KEY, igual que el resto de credenciales.
    """

    enabled: bool
    provider: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    dummy_delay: float
    future_api_key: Optional[str] = None


@dataclass(frozen=True)
class ReconciliationInspectionConfig:
    """Configuración de la automatización de inspecciones de
    reconciliación (Etapa 6.9, ver docs/ARQUITECTURA_PAPER_TRADING.md §23.13).

    Bloque **opcional** dentro de `paper_trading` en config.yaml: si no
    existe, se usan estos mismos valores por defecto (todos seguros: el
    scheduler queda deshabilitado). `enabled` aquí es un gate
    *independiente* de `paper_trading.enabled` -- controla únicamente si
    `inspection_scheduler.py` arranca su loop periódico, nunca si la
    inspección/reparación manual puede invocarse (§23.13).
    """

    enabled: bool = False
    interval_minutes: int = 60
    run_on_startup: bool = False
    deliver_alerts: bool = True
    max_alert_delivery_attempts: int = 3
    history_limit: int = 100
    pending_alert_batch_size: int = 100


@dataclass(frozen=True)
class InspectionNotificationsConfig:
    """Qué canales de entrega usa AlertDeliveryService (Etapa 6.10, ver
    docs/ARQUITECTURA_PAPER_TRADING.md §24.9).

    Bloque **opcional** dentro de `paper_trading` en config.yaml: si no
    existe, `logging=True` preserva exactamente el comportamiento ya
    aprobado en la Etapa 6.9 (`LoggingInspectionAlertSink` como único
    canal); los otros 4 son placeholders (§24.10, sin conexión real
    todavía) y quedan `False` por defecto.
    """

    logging: bool = True
    email: bool = False
    slack: bool = False
    telegram: bool = False
    webhook: bool = False


@dataclass(frozen=True)
class PaperTradingConfig:
    """Configuración de Paper Trading (Etapa 6.5).

    Distinta del resto de las secciones de Settings: todos los campos
    monetarios/de cantidad usan Decimal (nunca float), siguiendo la
    misma decisión ya tomada en todo el dominio de Paper Trading desde
    la Etapa 6.1 (ver docs/ARQUITECTURA_PAPER_TRADING.md). Por eso
    config.yaml -> paper_trading escribe esos valores entre comillas
    (como texto): así llegan a Python como `str` y se convierten
    directamente con `Decimal(value)`, nunca pasando por `float` primero
    (evitando el error de precisión de convertir un float ya impreciso).

    'enabled' es `false` por defecto (ver config.yaml): el repositorio,
    el servicio y la aplicación de Paper Trading pueden construirse y
    probarse sin que eso implique ejecutar ninguna orden real. Ninguna
    parte del proyecto activa Paper Trading automáticamente todavía (sin
    Strategy Engine, sin señales/IA ejecutando órdenes -- ver
    src/paper_trading/application.py).
    """

    enabled: bool
    database_path: str
    initial_capital: Decimal
    currency: str
    fee_rate: Decimal
    max_order_value: Decimal
    max_position_value: Decimal
    rules_version: str
    reconciliation_inspection: ReconciliationInspectionConfig = field(
        default_factory=ReconciliationInspectionConfig
    )
    inspection_notifications: InspectionNotificationsConfig = field(
        default_factory=InspectionNotificationsConfig
    )
    # Etapa 6.12: mismas credenciales que `Settings.telegram` (reutiliza
    # `TelegramSettings`, nunca un segundo sistema de configuración). El
    # flag que decide si el canal se activa sigue siendo
    # `inspection_notifications.telegram` (config.yaml), no una
    # variable de entorno nueva.
    telegram: TelegramSettings = field(default_factory=TelegramSettings)


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
    indicators: IndicatorSettings
    signals: SignalSettings
    ai_engine: AIEngineSettings
    paper_trading: PaperTradingConfig


def _load_yaml_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de configuración en: {config_path}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _validate_yaml_config(config)
    return config


_INDICATOR_INT_FIELDS = [
    "sma", "ema_fast", "ema_medium", "ema_slow", "rsi",
    "macd_fast", "macd_slow", "macd_signal", "bollinger_period", "atr", "adx",
]


def _validate_yaml_config(config: dict) -> None:
    required_keys = [
        "symbols", "interval_minutes", "database", "logging", "binance",
        "alerts", "indicators", "signals", "ai", "paper_trading",
    ]
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

    _validate_indicators_config(config["indicators"])
    _validate_signals_config(config["signals"])
    _validate_ai_config(config["ai"])
    _validate_paper_trading_config(config["paper_trading"])


def _validate_indicators_config(indicators_cfg: dict) -> None:
    required_fields = _INDICATOR_INT_FIELDS + ["bollinger_stddev", "vwap"]
    missing = [f for f in required_fields if f not in indicators_cfg]
    if missing:
        raise ValueError(
            f"Faltan campos obligatorios en config.yaml -> indicators: {', '.join(missing)}"
        )

    for field in _INDICATOR_INT_FIELDS:
        value = indicators_cfg[field]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"'indicators.{field}' debe ser un número entero mayor a 0.")

    stddev = indicators_cfg["bollinger_stddev"]
    if isinstance(stddev, bool) or not isinstance(stddev, (int, float)) or stddev <= 0:
        raise ValueError("'indicators.bollinger_stddev' debe ser un número mayor a 0.")

    if not isinstance(indicators_cfg["vwap"], bool):
        raise ValueError("'indicators.vwap' debe ser verdadero o falso (true/false).")


def _require_numeric(container: dict, field: str, path: str) -> None:
    value = container.get(field)
    if field not in container or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{path}.{field}' debe existir y ser un número.")


_SIGNAL_WEIGHT_FIELDS = ["trend", "ema", "macd", "rsi", "bollinger"]


def _validate_signals_config(signals_cfg: dict) -> None:
    for section in ["score", "weights", "confidence", "rules"]:
        if section not in signals_cfg:
            raise ValueError(f"Falta 'signals.{section}' en config.yaml.")

    score_cfg = signals_cfg["score"]
    for field in ["bullish", "neutral", "bearish"]:
        _require_numeric(score_cfg, field, "signals.score")

    weights_cfg = signals_cfg["weights"]
    for field in _SIGNAL_WEIGHT_FIELDS:
        _require_numeric(weights_cfg, field, "signals.weights")
        if weights_cfg[field] < 0:
            raise ValueError(f"'signals.weights.{field}' no puede ser negativo.")
    if sum(weights_cfg[field] for field in _SIGNAL_WEIGHT_FIELDS) <= 0:
        raise ValueError("La suma de 'signals.weights' debe ser mayor a 0.")

    confidence_cfg = signals_cfg["confidence"]
    for field in ["very_high", "high", "medium", "low"]:
        _require_numeric(confidence_cfg, field, "signals.confidence")

    rules_cfg = signals_cfg["rules"]
    for rule_name in ["trend", "ema", "rsi", "bollinger"]:
        if rule_name not in rules_cfg:
            raise ValueError(f"Falta 'signals.rules.{rule_name}' en config.yaml.")

    _require_numeric(rules_cfg["trend"], "neutral_band_pct", "signals.rules.trend")
    _require_numeric(rules_cfg["trend"], "strong_diff_pct", "signals.rules.trend")
    _require_numeric(rules_cfg["ema"], "neutral_band_pct", "signals.rules.ema")
    _require_numeric(rules_cfg["rsi"], "oversold", "signals.rules.rsi")
    _require_numeric(rules_cfg["rsi"], "overbought", "signals.rules.rsi")
    _require_numeric(rules_cfg["bollinger"], "proximity_pct", "signals.rules.bollinger")


_AI_PROVIDERS = ["dummy", "openai", "claude"]


def _validate_ai_config(ai_cfg: dict) -> None:
    required_fields = [
        "enabled", "provider", "model", "temperature", "max_tokens",
        "system_prompt", "dummy_delay",
    ]
    missing = [f for f in required_fields if f not in ai_cfg]
    if missing:
        raise ValueError(f"Faltan campos obligatorios en config.yaml -> ai: {', '.join(missing)}")

    if not isinstance(ai_cfg["enabled"], bool):
        raise ValueError("'ai.enabled' debe ser verdadero o falso (true/false).")

    if ai_cfg["provider"] not in _AI_PROVIDERS:
        raise ValueError(f"'ai.provider' debe ser uno de: {', '.join(_AI_PROVIDERS)}.")

    if not isinstance(ai_cfg["model"], str) or not ai_cfg["model"]:
        raise ValueError("'ai.model' debe ser un texto no vacío.")

    _require_numeric(ai_cfg, "temperature", "ai")
    # Rango razonable de "temperature" para proveedores de LLM típicos
    # (OpenAI/Anthropic): 0.0 (determinista) a 2.0 (máxima aleatoriedad).
    if not (0.0 <= ai_cfg["temperature"] <= 2.0):
        raise ValueError("'ai.temperature' debe estar entre 0.0 y 2.0.")

    if isinstance(ai_cfg["max_tokens"], bool) or not isinstance(ai_cfg["max_tokens"], int) or ai_cfg["max_tokens"] <= 0:
        raise ValueError("'ai.max_tokens' debe ser un número entero mayor a 0.")

    if not isinstance(ai_cfg["system_prompt"], str) or not ai_cfg["system_prompt"]:
        raise ValueError("'ai.system_prompt' debe ser un texto no vacío.")

    _require_numeric(ai_cfg, "dummy_delay", "ai")
    if ai_cfg["dummy_delay"] < 0:
        raise ValueError("'ai.dummy_delay' no puede ser negativo.")


def _require_decimal_string(container: dict, field: str, path: str) -> Decimal:
    """Exige que container[field] sea un str parseable como Decimal.

    Se guardan como texto en config.yaml (entre comillas) a propósito:
    así se leen directamente como Decimal, nunca pasando por float (ver
    PaperTradingConfig).
    """
    value = container.get(field)
    if field not in container or not isinstance(value, str):
        raise ValueError(
            f"'{path}.{field}' debe existir y ser un texto entre comillas (ej. \"100.0\"), "
            "no un número YAML sin comillas."
        )
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError(f"'{path}.{field}' debe ser un valor decimal válido (ej. \"100.0\").")


def _validate_paper_trading_config(pt_cfg: dict) -> None:
    required_fields = [
        "enabled", "database_path", "initial_capital", "currency",
        "fee_rate", "max_order_value", "max_position_value", "rules_version",
    ]
    missing = [f for f in required_fields if f not in pt_cfg]
    if missing:
        raise ValueError(
            f"Faltan campos obligatorios en config.yaml -> paper_trading: {', '.join(missing)}"
        )

    if not isinstance(pt_cfg["enabled"], bool):
        raise ValueError("'paper_trading.enabled' debe ser verdadero o falso (true/false).")

    if not isinstance(pt_cfg["database_path"], str) or not pt_cfg["database_path"]:
        raise ValueError("'paper_trading.database_path' debe ser un texto no vacío.")

    if not isinstance(pt_cfg["currency"], str) or not pt_cfg["currency"]:
        raise ValueError("'paper_trading.currency' debe ser un texto no vacío.")

    if not isinstance(pt_cfg["rules_version"], str) or not pt_cfg["rules_version"]:
        raise ValueError("'paper_trading.rules_version' debe ser un texto no vacío.")

    initial_capital = _require_decimal_string(pt_cfg, "initial_capital", "paper_trading")
    if initial_capital <= 0:
        raise ValueError("'paper_trading.initial_capital' debe ser mayor a 0.")

    fee_rate = _require_decimal_string(pt_cfg, "fee_rate", "paper_trading")
    if fee_rate < 0:
        raise ValueError("'paper_trading.fee_rate' no puede ser negativo.")

    max_order_value = _require_decimal_string(pt_cfg, "max_order_value", "paper_trading")
    if max_order_value <= 0:
        raise ValueError("'paper_trading.max_order_value' debe ser mayor a 0.")

    max_position_value = _require_decimal_string(pt_cfg, "max_position_value", "paper_trading")
    if max_position_value <= 0:
        raise ValueError("'paper_trading.max_position_value' debe ser mayor a 0.")

    if max_position_value < max_order_value:
        raise ValueError(
            "'paper_trading.max_position_value' debe ser mayor o igual a 'paper_trading.max_order_value'."
        )

    if "reconciliation_inspection" in pt_cfg:
        _validate_reconciliation_inspection_config(pt_cfg["reconciliation_inspection"])

    if "inspection_notifications" in pt_cfg:
        _validate_inspection_notifications_config(pt_cfg["inspection_notifications"])


def _validate_reconciliation_inspection_config(ri_cfg: dict) -> None:
    """Bloque opcional (Etapa 6.9, §23.13): cada campo es opcional
    individualmente (usa el default si falta), pero si está presente debe
    tener el tipo/rango correcto -- así una config.yaml de una etapa
    anterior (sin este bloque) sigue cargando sin cambios."""
    if "enabled" in ri_cfg and not isinstance(ri_cfg["enabled"], bool):
        raise ValueError("'paper_trading.reconciliation_inspection.enabled' debe ser verdadero o falso.")

    if "interval_minutes" in ri_cfg:
        value = ri_cfg["interval_minutes"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                "'paper_trading.reconciliation_inspection.interval_minutes' debe ser un entero >= 1."
            )

    if "run_on_startup" in ri_cfg and not isinstance(ri_cfg["run_on_startup"], bool):
        raise ValueError("'paper_trading.reconciliation_inspection.run_on_startup' debe ser verdadero o falso.")

    if "deliver_alerts" in ri_cfg and not isinstance(ri_cfg["deliver_alerts"], bool):
        raise ValueError("'paper_trading.reconciliation_inspection.deliver_alerts' debe ser verdadero o falso.")

    if "max_alert_delivery_attempts" in ri_cfg:
        value = ri_cfg["max_alert_delivery_attempts"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                "'paper_trading.reconciliation_inspection.max_alert_delivery_attempts' debe ser un entero >= 1."
            )

    if "history_limit" in ri_cfg:
        value = ri_cfg["history_limit"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("'paper_trading.reconciliation_inspection.history_limit' debe ser un entero >= 1.")

    if "pending_alert_batch_size" in ri_cfg:
        value = ri_cfg["pending_alert_batch_size"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                "'paper_trading.reconciliation_inspection.pending_alert_batch_size' debe ser un entero >= 1."
            )


def _validate_inspection_notifications_config(in_cfg: dict) -> None:
    """Bloque opcional (Etapa 6.10, §24.9): cada campo es opcional
    individualmente, pero si está presente debe ser un booleano."""
    for field_name in ("logging", "email", "slack", "telegram", "webhook"):
        if field_name in in_cfg and not isinstance(in_cfg[field_name], bool):
            raise ValueError(
                f"'paper_trading.inspection_notifications.{field_name}' debe ser verdadero o falso."
            )


def _parse_inspection_notifications_config(pt_cfg: dict) -> InspectionNotificationsConfig:
    in_cfg = pt_cfg.get("inspection_notifications", {})
    defaults = InspectionNotificationsConfig()
    return InspectionNotificationsConfig(
        logging=in_cfg.get("logging", defaults.logging),
        email=in_cfg.get("email", defaults.email),
        slack=in_cfg.get("slack", defaults.slack),
        telegram=in_cfg.get("telegram", defaults.telegram),
        webhook=in_cfg.get("webhook", defaults.webhook),
    )


def _parse_reconciliation_inspection_config(pt_cfg: dict) -> ReconciliationInspectionConfig:
    ri_cfg = pt_cfg.get("reconciliation_inspection", {})
    defaults = ReconciliationInspectionConfig()
    return ReconciliationInspectionConfig(
        enabled=ri_cfg.get("enabled", defaults.enabled),
        interval_minutes=ri_cfg.get("interval_minutes", defaults.interval_minutes),
        run_on_startup=ri_cfg.get("run_on_startup", defaults.run_on_startup),
        deliver_alerts=ri_cfg.get("deliver_alerts", defaults.deliver_alerts),
        max_alert_delivery_attempts=ri_cfg.get(
            "max_alert_delivery_attempts", defaults.max_alert_delivery_attempts
        ),
        history_limit=ri_cfg.get("history_limit", defaults.history_limit),
        pending_alert_batch_size=ri_cfg.get(
            "pending_alert_batch_size", defaults.pending_alert_batch_size
        ),
    )


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

    telegram_settings = TelegramSettings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        timeout_seconds=float(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "10")),
    )

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
        telegram=telegram_settings,
        ai=AISettings(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        ),
        external_data=ExternalDataSettings(
            coingecko_api_key=os.getenv("COINGECKO_API_KEY") or None,
            newsapi_api_key=os.getenv("NEWSAPI_API_KEY") or None,
        ),
        indicators=IndicatorSettings(
            sma=config["indicators"]["sma"],
            ema_fast=config["indicators"]["ema_fast"],
            ema_medium=config["indicators"]["ema_medium"],
            ema_slow=config["indicators"]["ema_slow"],
            rsi=config["indicators"]["rsi"],
            macd_fast=config["indicators"]["macd_fast"],
            macd_slow=config["indicators"]["macd_slow"],
            macd_signal=config["indicators"]["macd_signal"],
            bollinger_period=config["indicators"]["bollinger_period"],
            bollinger_stddev=config["indicators"]["bollinger_stddev"],
            atr=config["indicators"]["atr"],
            adx=config["indicators"]["adx"],
            vwap=config["indicators"]["vwap"],
        ),
        signals=SignalSettings(
            score=ScoreThresholds(
                bullish=config["signals"]["score"]["bullish"],
                neutral=config["signals"]["score"]["neutral"],
                bearish=config["signals"]["score"]["bearish"],
            ),
            weights=SignalWeights(
                trend=config["signals"]["weights"]["trend"],
                ema=config["signals"]["weights"]["ema"],
                macd=config["signals"]["weights"]["macd"],
                rsi=config["signals"]["weights"]["rsi"],
                bollinger=config["signals"]["weights"]["bollinger"],
            ),
            confidence=ConfidenceThresholds(
                very_high=config["signals"]["confidence"]["very_high"],
                high=config["signals"]["confidence"]["high"],
                medium=config["signals"]["confidence"]["medium"],
                low=config["signals"]["confidence"]["low"],
            ),
            rules=SignalRuleSettings(
                trend=TrendRuleSettings(
                    neutral_band_pct=config["signals"]["rules"]["trend"]["neutral_band_pct"],
                    strong_diff_pct=config["signals"]["rules"]["trend"]["strong_diff_pct"],
                ),
                ema=EMARuleSettings(
                    neutral_band_pct=config["signals"]["rules"]["ema"]["neutral_band_pct"],
                ),
                rsi=RSIRuleSettings(
                    oversold=config["signals"]["rules"]["rsi"]["oversold"],
                    overbought=config["signals"]["rules"]["rsi"]["overbought"],
                ),
                bollinger=BollingerRuleSettings(
                    proximity_pct=config["signals"]["rules"]["bollinger"]["proximity_pct"],
                ),
            ),
        ),
        ai_engine=AIEngineSettings(
            enabled=config["ai"]["enabled"],
            provider=config["ai"]["provider"],
            model=config["ai"]["model"],
            temperature=config["ai"]["temperature"],
            max_tokens=config["ai"]["max_tokens"],
            system_prompt=config["ai"]["system_prompt"],
            dummy_delay=config["ai"]["dummy_delay"],
            future_api_key=os.getenv("AI_FUTURE_API_KEY") or None,
        ),
        paper_trading=PaperTradingConfig(
            enabled=config["paper_trading"]["enabled"],
            database_path=config["paper_trading"]["database_path"],
            initial_capital=Decimal(config["paper_trading"]["initial_capital"]),
            currency=config["paper_trading"]["currency"],
            fee_rate=Decimal(config["paper_trading"]["fee_rate"]),
            max_order_value=Decimal(config["paper_trading"]["max_order_value"]),
            max_position_value=Decimal(config["paper_trading"]["max_position_value"]),
            rules_version=config["paper_trading"]["rules_version"],
            reconciliation_inspection=_parse_reconciliation_inspection_config(config["paper_trading"]),
            inspection_notifications=_parse_inspection_notifications_config(config["paper_trading"]),
            telegram=telegram_settings,
        ),
    )
