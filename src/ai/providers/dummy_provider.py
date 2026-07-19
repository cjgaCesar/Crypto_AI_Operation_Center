"""
Proveedor de IA simulado (Etapa 4).

Es el único AIProvider realmente conectado hoy: no llama a ninguna API ni
genera texto aleatorio (requisito explícito de esta etapa). Deriva una
respuesta determinista a partir de la línea "Signal Type: ..." que
PromptBuilder siempre escribe en el prompt (src/ai/prompt_builder.py) —el
mismo veredicto que el motor de señales de la Etapa 3 ya calculó—, y espera
'delay_seconds' antes de responder, para simular la latencia de un
proveedor real en pruebas manuales sin necesitar conexión de red.
"""

import time

from src.ai.base import AIProvider, AIProviderResponse
from src.ai.recommendation import RecommendationAction, RiskLevel

# (marcador de texto -> acción, riesgo, razón). El marcador es exactamente
# la línea que PromptBuilder._signal_section escribe para 'signal_type'.
_SIGNAL_TYPE_TO_ACTION = {
    "Signal Type: Bullish": (
        RecommendationAction.BUY, RiskLevel.MEDIUM,
        "El motor de señales (Etapa 3) reporta una tendencia alcista (signal_type=Bullish).",
    ),
    "Signal Type: Bearish": (
        RecommendationAction.SELL, RiskLevel.MEDIUM,
        "El motor de señales (Etapa 3) reporta una tendencia bajista (signal_type=Bearish).",
    ),
    "Signal Type: Neutral": (
        RecommendationAction.HOLD, RiskLevel.LOW,
        "El motor de señales (Etapa 3) no muestra una inclinación clara (signal_type=Neutral).",
    ),
}

_NO_SIGNAL_RESULT = (
    RecommendationAction.HOLD, RiskLevel.LOW,
    "Todavía no hay una señal disponible para este símbolo: se recomienda no actuar.",
)


class DummyProvider(AIProvider):
    """Proveedor simulado: útil para pruebas offline y para validar el
    pipeline completo (MarketContext -> PromptBuilder -> AIProvider ->
    AIRecommendation) sin depender de OpenAI ni Anthropic."""

    def __init__(self, delay_seconds: float = 0.0):
        self.delay_seconds = delay_seconds

    def generate(self, prompt: str) -> AIProviderResponse:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        action, risk, reasoning = self._infer_from_prompt(prompt)

        return AIProviderResponse(
            recommendation=action,
            confidence=60.0,
            risk_level=risk,
            reasoning=reasoning,
            advantages=[
                f"La acción sugerida ({action.value}) está alineada con el signal_type "
                "ya calculado por el motor de señales, sin necesitar recalcular nada."
            ],
            risks=[
                "DummyProvider es una simulación: no usa un modelo de lenguaje real, "
                "por lo que no debe usarse para decisiones reales todavía."
            ],
            summary=f"Recomendación simulada: {action.value}.",
            model="dummy-v1",
            raw_response=None,
        )

    @staticmethod
    def _infer_from_prompt(prompt: str) -> tuple[RecommendationAction, RiskLevel, str]:
        for marker, result in _SIGNAL_TYPE_TO_ACTION.items():
            if marker in prompt:
                return result
        return _NO_SIGNAL_RESULT
