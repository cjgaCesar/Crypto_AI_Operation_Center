"""
Motor de decisión de IA: lógica de negocio pura (sin I/O), igual en
espíritu a SignalEngine (src/signals/engine.py).

Recibe un MarketContext ya armado y devuelve una AIRecommendation. No sabe
leer de SQLite, no sabe consultar Binance y no conoce ningún Dashboard:
solo conoce un PromptBuilder (para construir el prompt) y un AIProvider
(para generar la respuesta). No recalcula ninguna regla ni ningún
indicador: solo interpreta lo que MarketContext ya trae del motor de
señales de la Etapa 3.
"""

import time
from datetime import datetime, timezone

from src.ai.base import AIProvider
from src.ai.context import MarketContext
from src.ai.prompt_builder import CURRENT_PROMPT_VERSION, PromptBuilder
from src.ai.recommendation import AIRecommendation


class DecisionEngine:
    def __init__(self, provider: AIProvider, prompt_builder: PromptBuilder, system_prompt: str):
        self.provider = provider
        self.prompt_builder = prompt_builder
        self.system_prompt = system_prompt

    def decide(self, context: MarketContext) -> AIRecommendation:
        """Construye el prompt, llama al proveedor y arma la
        AIRecommendation final. No atrapa ninguna excepción que lance
        provider.generate(): si el proveedor falla (ej. un error de red de
        un proveedor real en el futuro), el error se propaga tal cual a
        quien llamó a decide() (AIService), en vez de ocultarse."""
        prompt = self.prompt_builder.build(context, self.system_prompt)

        # time.perf_counter(): reloj monotónico, mide únicamente la
        # duración de la llamada al proveedor (no el armado del prompt ni
        # lo que pase después), y no se ve afectado por ajustes del reloj
        # del sistema (a diferencia de datetime.now()).
        start = time.perf_counter()
        response = self.provider.generate(prompt)
        processing_time_ms = (time.perf_counter() - start) * 1000

        return AIRecommendation(
            exchange=context.exchange,
            symbol=context.symbol,
            timestamp=datetime.now(timezone.utc),
            recommendation=response.recommendation,
            confidence=response.confidence,
            risk_level=response.risk_level,
            reasoning=response.reasoning,
            advantages=response.advantages,
            risks=response.risks,
            summary=response.summary,
            provider=type(self.provider).__name__,
            model=response.model,
            prompt_version=CURRENT_PROMPT_VERSION,
            processing_time_ms=processing_time_ms,
            raw_response=response.raw_response,
        )
