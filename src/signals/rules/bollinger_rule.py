"""
BollingerRule: determina la posición del precio actual respecto de las
Bandas de Bollinger ya calculadas por IndicatorEngine.

Devuelve un RuleResult[BollingerLabel]. 'strength' mide qué tan adentro de
la zona de proximidad (o más allá de la banda) está el precio: 0 justo al
empezar la zona de proximidad, 1 exactamente en la banda o más allá
(recortado a 1).

A diferencia de las demás reglas, también necesita el precio actual
(market_data): las bandas por sí solas no indican dónde está el precio
dentro de ellas.
"""

from typing import Optional

from src.signals.enums import BollingerLabel, Direction
from src.signals.rule_result import RuleResult
from src.utils.config import BollingerRuleSettings


class BollingerRule:
    def __init__(self, settings: BollingerRuleSettings):
        self.settings = settings

    def evaluate(
        self,
        price: Optional[float],
        bollinger_upper: Optional[float],
        bollinger_lower: Optional[float],
    ) -> RuleResult[BollingerLabel]:
        if (
            price is None
            or bollinger_upper is None
            or bollinger_lower is None
            or bollinger_upper <= bollinger_lower
        ):
            return RuleResult[BollingerLabel](
                direction=Direction.NEUTRAL,
                strength=0.0,
                reason="No hay suficiente historial de Bollinger todavía.",
                label=BollingerLabel.INSIDE_BANDS,
            )

        band_width = bollinger_upper - bollinger_lower
        proximity = band_width * (self.settings.proximity_pct / 100)
        upper_zone_start = bollinger_upper - proximity
        lower_zone_start = bollinger_lower + proximity

        if price >= upper_zone_start:
            strength = min((price - upper_zone_start) / proximity, 1.0) if proximity else 1.0
            return RuleResult[BollingerLabel](
                direction=Direction.BULLISH,
                strength=strength,
                reason=f"Precio ({price:.4f}) cerca o sobre la banda superior ({bollinger_upper:.4f}).",
                label=BollingerLabel.UPPER_BAND,
            )
        if price <= lower_zone_start:
            strength = min((lower_zone_start - price) / proximity, 1.0) if proximity else 1.0
            return RuleResult[BollingerLabel](
                direction=Direction.BEARISH,
                strength=strength,
                reason=f"Precio ({price:.4f}) cerca o bajo la banda inferior ({bollinger_lower:.4f}).",
                label=BollingerLabel.LOWER_BAND,
            )
        return RuleResult[BollingerLabel](
            direction=Direction.NEUTRAL,
            strength=0.0,
            reason=f"Precio ({price:.4f}) dentro de las bandas, sin cercanía a ninguna.",
            label=BollingerLabel.INSIDE_BANDS,
        )
