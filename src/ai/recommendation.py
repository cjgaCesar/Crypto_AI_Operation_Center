"""
Recomendación estructurada de IA (Etapa 4).

AIRecommendation es la salida final del AI Decision Engine: una
interpretación de un SignalSnapshot ya generado por el motor de reglas
(Etapa 3), nunca un reemplazo de esa señal. La IA no recalcula 'score',
'confidence' ni ninguna regla: solo interpreta, explica y prioriza lo que
el motor de señales ya decidió.

Nota de conceptos (para no repetir la confusión que motivó la revisión 2 de
la Etapa 3, ver docs/ALCANCE_ETAPA_3.md):
- 'confidence' aquí es la certeza AUTOREPORTADA por el proveedor de IA
  sobre SU PROPIA recomendación (0.0-100.0, numérica). No es lo mismo que
  SignalSnapshot.confidence (Etapa 3), que mide el acuerdo entre las 5
  reglas del motor de señales y es un ConfidenceLevel categórico.
- 'risk_level' es la evaluación de riesgo de la IA sobre actuar según esta
  recomendación: un concepto nuevo de esta etapa, sin equivalente en la
  Etapa 3.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.ai.prompt_builder import PromptVersion


class RecommendationAction(str, Enum):
    """Acción sugerida por la IA. Relacionada con, pero no igual a,
    SignalType (Etapa 3): SignalType es el veredicto del motor de reglas;
    RecommendationAction es lo que la IA decide recomendar a partir de él.

    Tiene 7 niveles (no solo Buy/Sell/Hold) para que un proveedor real
    pueda expresar matices de convicción (ej. "Strong Buy" vs "Weak Buy").
    Hoy DummyProvider solo usa BUY/SELL/HOLD (ver
    src/ai/providers/dummy_provider.py); los niveles fuertes/débiles quedan
    disponibles para cuando se conecte un proveedor real. Los 3 valores
    usados hoy mantienen exactamente el mismo texto que antes de ampliar
    este enum, así que ninguna AIRecommendation ya guardada deja de poder
    leerse."""

    STRONG_BUY = "Strong Buy"
    BUY = "Buy"
    WEAK_BUY = "Weak Buy"
    HOLD = "Hold"
    WEAK_SELL = "Weak Sell"
    SELL = "Sell"
    STRONG_SELL = "Strong Sell"


class RiskLevel(str, Enum):
    """Nivel de riesgo que la IA asigna a seguir su propia recomendación.

    5 niveles (antes 3), igual en espíritu a ConfidenceLevel (Etapa 3).
    DummyProvider hoy solo usa LOW/MEDIUM (comportamiento sin cambios); los
    extremos (VERY_LOW/VERY_HIGH) quedan disponibles para un proveedor
    real. LOW/MEDIUM/HIGH mantienen el mismo texto que antes de ampliar
    este enum."""

    VERY_LOW = "Very Low"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very High"


class AIRecommendation(BaseModel):
    """Resultado final del AI Decision Engine para un (exchange, symbol)."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    timestamp: datetime

    recommendation: RecommendationAction
    confidence: float = Field(ge=0.0, le=100.0)
    risk_level: RiskLevel

    reasoning: str = Field(min_length=1)
    advantages: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: PromptVersion

    # Cuánto tardó ÚNICAMENTE la llamada a AIProvider.generate() (no el
    # armado del prompt ni el guardado), medido por DecisionEngine con
    # time.perf_counter() (reloj monotónico: no se ve afectado por ajustes
    # del reloj del sistema, a diferencia de datetime.now()).
    processing_time_ms: float = Field(ge=0.0)

    # Respuesta cruda del proveedor (ej. el JSON/texto tal cual lo devolvió
    # OpenAI/Claude), para auditoría y depuración cuando se conecte un
    # proveedor real. DummyProvider siempre devuelve None (no hay ninguna
    # respuesta "cruda": la genera ella misma ya estructurada).
    raw_response: Optional[str] = None
