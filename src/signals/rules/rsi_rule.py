"""
RSIRule: clasifica el RSI ya calculado por IndicatorEngine en zonas de
sobreventa/sobrecompra.

Devuelve un RuleResult[RSILabel]. 'strength' mide qué tan lejos está el RSI
del umbral configurado, respecto del extremo posible (100 para
sobrecompra, 0 para sobreventa): justo en el umbral la fuerza es 0; en el
extremo, 1.

Nota de diseño (ya documentada desde la primera versión de esta regla):
"Overbought" se trata como inclinación alcista y "Oversold" como bajista
(seguimiento de tendencia), no la interpretación contraria de "comprar en
sobreventa".
"""

from typing import Optional

from src.signals.enums import Direction, RSILabel
from src.signals.rule_result import RuleResult
from src.utils.config import RSIRuleSettings


class RSIRule:
    def __init__(self, settings: RSIRuleSettings):
        self.settings = settings

    def evaluate(self, rsi: Optional[float]) -> RuleResult[RSILabel]:
        if rsi is None:
            return RuleResult[RSILabel](
                direction=Direction.NEUTRAL,
                strength=0.0,
                reason="No hay suficiente historial de RSI todavía.",
                label=RSILabel.NEUTRAL,
            )

        if rsi <= self.settings.oversold:
            remaining_range = self.settings.oversold or 1.0
            strength = min((self.settings.oversold - rsi) / remaining_range, 1.0)
            return RuleResult[RSILabel](
                direction=Direction.BEARISH,
                strength=strength,
                reason=f"RSI en {rsi:.2f}, por debajo del umbral de sobreventa ({self.settings.oversold}).",
                label=RSILabel.OVERSOLD,
            )

        if rsi >= self.settings.overbought:
            remaining_range = (100 - self.settings.overbought) or 1.0
            strength = min((rsi - self.settings.overbought) / remaining_range, 1.0)
            return RuleResult[RSILabel](
                direction=Direction.BULLISH,
                strength=strength,
                reason=f"RSI en {rsi:.2f}, por encima del umbral de sobrecompra ({self.settings.overbought}).",
                label=RSILabel.OVERBOUGHT,
            )

        return RuleResult[RSILabel](
            direction=Direction.NEUTRAL,
            strength=0.0,
            reason=f"RSI en {rsi:.2f}, dentro de la zona neutral.",
            label=RSILabel.NEUTRAL,
        )
