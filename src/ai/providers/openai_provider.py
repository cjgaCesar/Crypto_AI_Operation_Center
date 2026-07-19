"""
Proveedor de IA usando OpenAI (Etapa 4, estructura preparada, NO conectado).

Sigue el mismo patrón que PostgresMarketDataRepository/PostgresIndicatorRepository/
PostgresSignalRepository (src/database/, src/signals/postgres_repository.py):
existe para que, cuando se autorice conectar la API real de OpenAI, solo
haya que implementar 'generate()' aquí, usando 'api_key'/'model'/
'temperature'/'max_tokens' (ya preparados en Settings.ai / Settings.ai_engine,
ver src/utils/config.py), sin tocar DecisionEngine, PromptBuilder ni ningún
otro módulo del proyecto.
"""

from src.ai.base import AIProvider, AIProviderResponse


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str, temperature: float, max_tokens: int):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str) -> AIProviderResponse:
        raise NotImplementedError(
            "OpenAIProvider todavía no está conectado a la API real de OpenAI "
            "(fuera de alcance de la Etapa 4). Usar DummyProvider mientras tanto."
        )
