"""
Tema visual del Dashboard (Etapa 5, Iteración 5.3).

Centraliza la paleta de colores en un solo lugar, para que ningún
componente ni página tenga un color de texto suelto. Esta iteración solo
define los tokens básicos y 3 funciones puras que deciden qué color usar
según un valor de dominio (SignalType, RiskLevel, una variación numérica);
no aplica todavía un rediseño visual completo ni CSS global (eso es una
iteración futura).

Estas funciones son puras: no importan Streamlit, no dependen de nada más
que del valor recibido, y siempre devuelven un color válido (nunca None) —
un valor desconocido o None cae en COLOR_NEUTRAL, nunca en una excepción.
"""

from typing import Optional

from src.ai.recommendation import RiskLevel
from src.signals.enums import SignalType

COLOR_BACKGROUND = "#0B1220"
COLOR_PANEL = "#111827"
COLOR_BORDER = "#334155"
COLOR_TEXT_PRIMARY = "#F8FAFC"
COLOR_TEXT_SECONDARY = "#CBD5E1"
COLOR_POSITIVE = "#22C55E"
COLOR_NEGATIVE = "#EF4444"
COLOR_WARNING = "#F59E0B"
COLOR_INFO = "#38BDF8"
COLOR_ACCENT = "#3B82F6"
COLOR_AI = "#8B5CF6"
COLOR_NEUTRAL = "#94A3B8"

_SIGNAL_COLORS = {
    SignalType.BULLISH: COLOR_POSITIVE,
    SignalType.BEARISH: COLOR_NEGATIVE,
    SignalType.NEUTRAL: COLOR_NEUTRAL,
}

_RISK_COLORS = {
    RiskLevel.VERY_LOW: COLOR_POSITIVE,
    RiskLevel.LOW: COLOR_POSITIVE,
    RiskLevel.MEDIUM: COLOR_WARNING,
    RiskLevel.HIGH: COLOR_NEGATIVE,
    RiskLevel.VERY_HIGH: COLOR_NEGATIVE,
}


def get_signal_color(signal_type: Optional[SignalType]) -> str:
    """Color asociado a un SignalType. Cualquier valor que no sea un
    SignalType reconocido (incluyendo None) devuelve COLOR_NEUTRAL."""
    if signal_type is None:
        return COLOR_NEUTRAL
    return _SIGNAL_COLORS.get(signal_type, COLOR_NEUTRAL)


def get_risk_color(risk_level: Optional[RiskLevel]) -> str:
    """Color asociado a un RiskLevel. Cualquier valor que no sea un
    RiskLevel reconocido (incluyendo None) devuelve COLOR_NEUTRAL."""
    if risk_level is None:
        return COLOR_NEUTRAL
    return _RISK_COLORS.get(risk_level, COLOR_NEUTRAL)


def get_change_color(value: Optional[float]) -> str:
    """Color asociado a una variación numérica (ej. price_change_percent_24h):
    positiva -> COLOR_POSITIVE, negativa -> COLOR_NEGATIVE, cero o
    ausente -> COLOR_NEUTRAL."""
    if value is None or value == 0:
        return COLOR_NEUTRAL
    return COLOR_POSITIVE if value > 0 else COLOR_NEGATIVE
