"""
Resultado estructurado de una regla individual de señales.

Reemplaza el diseño anterior (cada regla devolvía un Enum propio, ej.
TrendResult.STRONG_BULLISH, directamente como string). Ahora toda regla
devuelve un RuleResult:

- direction: inclinación de la regla (Direction: BULLISH/NEUTRAL/BEARISH).
- strength: magnitud de la señal, normalizada de 0.0 a 1.0 (0 = sin señal
  direccional, 1 = señal máxima según los umbrales configurados de esa
  regla en particular). Pydantic rechaza cualquier valor fuera de ese rango.
- reason: explicación en texto de por qué se llegó a ese resultado, para
  que una futura IA pueda explicar la señal sin recalcular nada (Etapa 4).
- label: etiqueta específica y más detallada que 'direction' (ej. "Strong
  Bullish", "Oversold", "Bullish Cross", "Upper Band"). Es lo que se
  guarda en los campos trend/ema_signal/macd_signal/rsi_signal/
  bollinger_signal de SignalSnapshot.

RuleResult es GENÉRICO sobre el tipo de 'label' (RuleResult[TrendLabel],
RuleResult[EMALabel], etc.): cada regla tiene su propio vocabulario de
etiquetas (TrendLabel tiene 5 valores; EMALabel, MACDLabel, RSILabel y
BollingerLabel tienen 3 cada una), y varios de esos valores de texto se
repiten entre enums distintos (ej. "Neutral" existe en los 5). Usar un
Union simple (label: Union[TrendLabel, EMALabel, ...]) sería ambiguo en
esos casos: Pydantic podría validar "Neutral" contra cualquiera de los
enums que lo contienen, sin garantía de cuál. Al parametrizar RuleResult
por regla (RuleResult[TrendLabel] para TrendRule, etc.), cada instancia
valida su 'label' contra el Enum exacto de esa regla, sin ambigüedad.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from src.signals.enums import Direction

LabelT = TypeVar("LabelT")


class RuleResult(BaseModel, Generic[LabelT]):
    direction: Direction
    strength: float = Field(ge=0.0, le=1.0)
    reason: str
    label: LabelT
