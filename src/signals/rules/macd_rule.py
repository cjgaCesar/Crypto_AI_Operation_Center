"""
MACDRule: compara la línea MACD contra su línea de señal, ambas ya
calculadas por IndicatorEngine.

Devuelve un RuleResult[MACDLabel]. 'strength' es la divergencia relativa
entre ambas líneas, normalizada con la suma de sus magnitudes absolutas (0
cuando son iguales, cercano a 1 cuando una domina claramente a la otra). No
tiene umbrales configurables: compara directamente dos valores que
IndicatorEngine ya calculó con sus propios periodos (macd_fast/slow/signal,
configurables en indicators.*).

Nota (ya documentada desde la primera versión de esta regla): refleja la
relación ACTUAL entre ambas líneas, no necesariamente que el cruce haya
ocurrido en este instante.
"""

from typing import Optional

from src.signals.enums import Direction, MACDLabel
from src.signals.rule_result import RuleResult


class MACDRule:
    def evaluate(
        self, macd_line: Optional[float], macd_signal: Optional[float]
    ) -> RuleResult[MACDLabel]:
        if macd_line is None or macd_signal is None:
            return RuleResult[MACDLabel](
                direction=Direction.NEUTRAL,
                strength=0.0,
                reason="No hay suficiente historial de MACD todavía.",
                label=MACDLabel.NEUTRAL,
            )

        diff = macd_line - macd_signal
        denominator = abs(macd_line) + abs(macd_signal)
        strength = min(abs(diff) / denominator, 1.0) if denominator else 0.0

        if diff > 0:
            return RuleResult[MACDLabel](
                direction=Direction.BULLISH,
                strength=strength,
                reason=f"MACD ({macd_line:.4f}) por encima de su línea de señal ({macd_signal:.4f}).",
                label=MACDLabel.BULLISH_CROSS,
            )
        if diff < 0:
            return RuleResult[MACDLabel](
                direction=Direction.BEARISH,
                strength=strength,
                reason=f"MACD ({macd_line:.4f}) por debajo de su línea de señal ({macd_signal:.4f}).",
                label=MACDLabel.BEARISH_CROSS,
            )
        return RuleResult[MACDLabel](
            direction=Direction.NEUTRAL,
            strength=0.0,
            reason="MACD igual a su línea de señal.",
            label=MACDLabel.NEUTRAL,
        )
