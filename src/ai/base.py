"""
Interfaz común que debe cumplir cualquier proveedor de IA.

Sigue el mismo patrón que ExchangeClient (src/market/base.py) y
SignalRepository (src/signals/base.py): DecisionEngine no sabe si el
proveedor activo es DummyProvider, OpenAIProvider o ClaudeProvider, solo
que cumple este contrato. Cambiar de proveedor (ej. de Dummy a OpenAI en
una etapa futura) solo requiere instanciar una clase distinta en
build_services() (src/main.py); nada más del proyecto necesita cambiar.
"""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from src.ai.recommendation import RecommendationAction, RiskLevel


class AIProviderResponse(BaseModel):
    """Respuesta cruda de un proveedor de IA, antes de convertirse en
    AIRecommendation. DecisionEngine agrega los campos que el proveedor no
    conoce (exchange, symbol, timestamp, provider, prompt_version,
    processing_time_ms) y copia el resto (incluyendo 'raw_response') tal
    cual."""

    recommendation: RecommendationAction
    confidence: float = Field(ge=0.0, le=100.0)
    risk_level: RiskLevel
    reasoning: str = Field(min_length=1)
    advantages: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    model: str = Field(min_length=1)

    # Respuesta cruda del proveedor (ej. el texto/JSON tal cual lo devolvió
    # OpenAI/Claude), para auditoría y depuración. DummyProvider siempre
    # devuelve None: no hay ninguna respuesta "cruda" que preservar.
    raw_response: Optional[str] = None


class AIProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> AIProviderResponse:
        """Genera una respuesta estructurada a partir de un prompt ya
        armado por PromptBuilder. No sabe de dónde vino el prompt (Binance,
        SQLite) ni qué se hace después con la respuesta (DecisionEngine)."""
