"""
Proveedor de IA usando Claude/Anthropic (Etapa 4, estructura preparada, NO conectado).

Sigue el mismo patrón que OpenAIProvider (src/ai/providers/openai_provider.py)
y que los repositorios Postgres ya existentes en el proyecto: existe para
que, cuando se autorice conectar la API real de Anthropic, solo haya que
implementar 'generate()' aquí, usando 'api_key'/'model'/'temperature'/
'max_tokens' (ya preparados en Settings.ai / Settings.ai_engine, ver
src/utils/config.py), sin tocar DecisionEngine, PromptBuilder ni ningún
otro módulo del proyecto.
"""

from src.ai.base import AIProvider, AIProviderResponse


class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str, model: str, temperature: float, max_tokens: int):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str) -> AIProviderResponse:
        raise NotImplementedError(
            "ClaudeProvider todavía no está conectado a la API real de Anthropic "
            "(fuera de alcance de la Etapa 4). Usar DummyProvider mientras tanto."
        )
