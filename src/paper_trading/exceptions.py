"""
Excepciones del dominio de Paper Trading (Etapa 6.1).

Se declaran ahora, aunque ningún motor de esta iteración las lance
todavía (esta etapa no incluye ningún Engine, ver src/paper_trading/
__init__.py), para que la Etapa 6.2 (motores puros, ver
docs/ARQUITECTURA_PAPER_TRADING.md §19) no tenga que diseñar la
jerarquía de errores desde cero: son invariantes que la arquitectura ya
identificó como responsabilidad del futuro motor, no de un modelo
individual (ej. un over-fill cruza Order + Execution, ver §4 "casos
especiales" -- ningún modelo por sí solo puede validarlo).
"""


class PaperTradingDomainError(Exception):
    """Error base de todo el dominio de Paper Trading."""


class InvalidOrderTransitionError(PaperTradingDomainError):
    """Se intentó una transición de estado de Order no permitida.

    Ver ARQUITECTURA_PAPER_TRADING.md §4 (matriz de transiciones válidas
    y transiciones inválidas).
    """


class OverFillError(PaperTradingDomainError):
    """Una Execution superaría la cantidad restante de la Order que llena.

    Invariante dura (ver ARQUITECTURA_PAPER_TRADING.md §4, caso especial
    "over-fill"): debe rechazarse ruidosamente, nunca recortarse en
    silencio.
    """
