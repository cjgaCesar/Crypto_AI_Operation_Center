"""
EMARule: detecta un cruce de corto plazo entre la EMA rápida y la EMA
media (distinto de TrendRule, que evalúa la alineación completa de las 3
EMA para la tendencia general).

Devuelve un RuleResult[EMALabel]. 'strength' se normaliza usando 10 veces
la banda neutral configurada como referencia de "señal máxima": es una
elección de diseño razonable para que el resultado sature en 1.0 ante un
cruce claro, ya que EMARule (a diferencia de TrendRule) no tiene una
categoría "Strong" con su propio umbral configurado.
"""

from typing import Optional

from src.signals.enums import Direction, EMALabel
from src.signals.rule_result import RuleResult
from src.utils.config import EMARuleSettings

_STRENGTH_REFERENCE_MULTIPLIER = 10


class EMARule:
    def __init__(self, settings: EMARuleSettings):
        self.settings = settings

    def evaluate(
        self, ema_fast: Optional[float], ema_medium: Optional[float]
    ) -> RuleResult[EMALabel]:
        if ema_fast is None or ema_medium is None or ema_medium == 0:
            return RuleResult[EMALabel](
                direction=Direction.NEUTRAL,
                strength=0.0,
                reason="No hay suficiente historial de EMA todavía.",
                label=EMALabel.NEUTRAL,
            )

        diff_pct = (ema_fast - ema_medium) / abs(ema_medium) * 100
        reference = self.settings.neutral_band_pct * _STRENGTH_REFERENCE_MULTIPLIER

        if diff_pct > self.settings.neutral_band_pct:
            strength = min(diff_pct / reference, 1.0) if reference else 1.0
            return RuleResult[EMALabel](
                direction=Direction.BULLISH,
                strength=strength,
                reason=f"EMA rápida está {diff_pct:+.2f}% sobre la EMA media.",
                label=EMALabel.BULLISH,
            )
        if diff_pct < -self.settings.neutral_band_pct:
            strength = min(abs(diff_pct) / reference, 1.0) if reference else 1.0
            return RuleResult[EMALabel](
                direction=Direction.BEARISH,
                strength=strength,
                reason=f"EMA rápida está {diff_pct:+.2f}% bajo la EMA media.",
                label=EMALabel.BEARISH,
            )
        return RuleResult[EMALabel](
            direction=Direction.NEUTRAL,
            strength=0.0,
            reason=f"EMA rápida y media muy cercanas ({diff_pct:+.2f}%).",
            label=EMALabel.NEUTRAL,
        )
