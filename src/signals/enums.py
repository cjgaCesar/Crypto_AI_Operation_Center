"""
Enums comunes del motor de señales (Etapa 3).

Se centralizan aquí para que las 5 reglas, el agregador, el motor y el
modelo RuleResult reutilicen exactamente los mismos valores, en vez de
tener strings sueltos repartidos por el módulo.
"""

from enum import Enum


class Direction(str, Enum):
    """Inclinación direccional de una regla individual (RuleResult.direction)."""

    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"


class TrendStrength(str, Enum):
    """Fuerza de la tendencia general, derivada de TrendRule."""

    WEAK = "Weak"
    MEDIUM = "Medium"
    STRONG = "Strong"


class ConfidenceLevel(str, Enum):
    """Nivel de confianza de la señal agregada, según el acuerdo entre reglas."""

    VERY_LOW = "Very Low"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very High"


class SignalType(str, Enum):
    """Clasificación de la señal agregada FINAL (score ya ponderado),
    usando los umbrales de config.yaml -> signals.score.

    Distinta de 'Direction': Direction es la inclinación de una regla
    individual; SignalType es el veredicto general de toda la señal.
    """

    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"


# --- Enums de "label" (categoría detallada) de cada regla individual ------
#
# RuleResult.label usa uno de estos 5 enums, según qué regla lo produjo (ver
# src/signals/rule_result.py, que lo tipa como genérico). No son strings
# sueltos: cada valor de texto sigue siendo legible (ej. "Strong Bullish"),
# pero internamente son miembros de un Enum específico de esa regla.


class TrendLabel(str, Enum):
    STRONG_BULLISH = "Strong Bullish"
    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"
    STRONG_BEARISH = "Strong Bearish"


class EMALabel(str, Enum):
    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"


class MACDLabel(str, Enum):
    BULLISH_CROSS = "Bullish Cross"
    NEUTRAL = "Neutral"
    BEARISH_CROSS = "Bearish Cross"


class RSILabel(str, Enum):
    OVERSOLD = "Oversold"
    NEUTRAL = "Neutral"
    OVERBOUGHT = "Overbought"


class BollingerLabel(str, Enum):
    UPPER_BAND = "Upper Band"
    INSIDE_BANDS = "Inside Bands"
    LOWER_BAND = "Lower Band"
