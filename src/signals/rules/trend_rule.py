"""
TrendRule: estima la dirección general del mercado a partir de la
alineación de las 3 medias móviles exponenciales (EMA rápida, media y
lenta) ya calculadas por IndicatorEngine.

Devuelve un RuleResult[TrendLabel] (nunca un string suelto): 'direction'
indica la inclinación (BULLISH/NEUTRAL/BEARISH), 'strength' (0 a 1) qué tan
cerca está esa diferencia del umbral "fuerte" configurado (satura en 1.0
cuando se alcanza 'strong_diff_pct'), y 'label' la categoría detallada
(TrendLabel: Strong Bullish/Bullish/Neutral/Bearish/Strong Bearish) que se
guarda en el campo 'trend' de SignalSnapshot.
"""

from typing import Optional

from src.signals.enums import Direction, TrendLabel
from src.signals.rule_result import RuleResult
from src.utils.config import TrendRuleSettings


class TrendRule:
    def __init__(self, settings: TrendRuleSettings):
        self.settings = settings

    def evaluate(
        self,
        ema_fast: Optional[float],
        ema_medium: Optional[float],
        ema_slow: Optional[float],
    ) -> RuleResult[TrendLabel]:
        if ema_fast is None or ema_medium is None or ema_slow is None or ema_slow == 0:
            return RuleResult[TrendLabel](
                direction=Direction.NEUTRAL,
                strength=0.0,
                reason="No hay suficiente historial de EMA todavía para evaluar la tendencia.",
                label=TrendLabel.NEUTRAL,
            )

        diff_pct = (ema_fast - ema_slow) / abs(ema_slow) * 100

        if abs(diff_pct) <= self.settings.neutral_band_pct:
            return RuleResult[TrendLabel](
                direction=Direction.NEUTRAL,
                strength=0.0,
                reason=f"EMA rápida y lenta muy cercanas ({diff_pct:+.2f}%).",
                label=TrendLabel.NEUTRAL,
            )

        strength = min(abs(diff_pct) / self.settings.strong_diff_pct, 1.0)

        if diff_pct > 0:
            aligned = ema_fast > ema_medium > ema_slow
            label = TrendLabel.STRONG_BULLISH if (aligned and strength >= 1.0) else TrendLabel.BULLISH
            reason = f"EMA rápida {diff_pct:+.2f}% sobre la EMA lenta"
            reason += ", con las 3 EMA alineadas al alza." if aligned else "."
            return RuleResult[TrendLabel](
                direction=Direction.BULLISH, strength=strength, reason=reason, label=label
            )

        aligned = ema_fast < ema_medium < ema_slow
        label = TrendLabel.STRONG_BEARISH if (aligned and strength >= 1.0) else TrendLabel.BEARISH
        reason = f"EMA rápida {diff_pct:+.2f}% bajo la EMA lenta"
        reason += ", con las 3 EMA alineadas a la baja." if aligned else "."
        return RuleResult[TrendLabel](
            direction=Direction.BEARISH, strength=strength, reason=reason, label=label
        )
