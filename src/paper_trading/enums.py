"""
Enums del dominio de Paper Trading (Etapa 6.1).

Mismo criterio que src/signals/enums.py y src/ai/recommendation.py:
str + Enum, para que el valor sea directamente serializable y legible.

Alcance inicial aprobado (ver docs/ARQUITECTURA_PAPER_TRADING.md, §5,
§5.1 y §20): solo MARKET y solo LONG están en uso. LIMIT, SHORT y
STRATEGY quedan reservados en sus enums, sin usarse todavía -- mismo
criterio ya aplicado en el proyecto a RecommendationAction/RiskLevel
(src/ai/recommendation.py): un valor reservado no es un valor prohibido,
solo un valor que ningún motor produce todavía. Ningún motor existe
todavía en esta iteración (ver src/paper_trading/__init__.py).
"""

from enum import Enum


class OrderSide(str, Enum):
    """Sentido de una orden."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Tipo de orden.

    Solo MARKET está implementado en esta iteración. LIMIT queda
    reservado (diferido a una iteración futura, ver
    ARQUITECTURA_PAPER_TRADING.md §5 y §20: los datos de mercado
    actuales, un solo precio por ciclo sin bid/ask/profundidad, no
    permiten simular su activación con fidelidad suficiente todavía).
    """

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    """Estado del ciclo de vida de una orden (ver ARQUITECTURA_PAPER_TRADING.md §4)."""

    NEW = "NEW"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionSide(str, Enum):
    """Lado de una posición abierta.

    Solo LONG/FLAT están implementados en esta iteración. SHORT queda
    reservado (diferido, ver ARQUITECTURA_PAPER_TRADING.md §5.1: un
    modelo de solo efectivo no puede acotar la pérdida potencial de un
    corto sin un modelo de margen/colateral, todavía sin diseñar).
    """

    LONG = "LONG"
    FLAT = "FLAT"
    SHORT = "SHORT"


class TradeSide(str, Enum):
    """Lado de un Trade (round-trip cerrado, ver ARQUITECTURA_PAPER_TRADING.md §2.3).

    Mismo criterio que PositionSide: solo LONG está en uso; SHORT queda
    reservado (ver §5.1).
    """

    LONG = "LONG"
    SHORT = "SHORT"


class OrderSource(str, Enum):
    """Origen de una orden, para trazabilidad (ver ARQUITECTURA_PAPER_TRADING.md §15).

    MANUAL y AI_RECOMMENDATION están en uso en esta iteración. STRATEGY
    queda reservado: no existe todavía ningún StrategyEngine que lo
    produzca (etapa futura, ver ARQUITECTURA_PAPER_TRADING.md §15).
    """

    MANUAL = "MANUAL"
    AI_RECOMMENDATION = "AI_RECOMMENDATION"
    STRATEGY = "STRATEGY"
