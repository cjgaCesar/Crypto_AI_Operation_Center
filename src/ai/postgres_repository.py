"""
Implementación futura de AIRepository usando PostgreSQL.

Este archivo NO se usa todavía en ningún lugar del proyecto. Igual que
src/database/postgres_repository.py (para market_data),
src/database/postgres_indicator_repository.py (para market_indicators) y
src/signals/postgres_repository.py (para market_signals), se deja
preparado para cuando se decida migrar de SQLite a PostgreSQL.

La tabla equivalente deberá incluir las mismas columnas que usa hoy
SQLiteAIRepository: exchange, symbol, recommendation, confidence,
risk_level, reasoning, advantages, risks, summary, provider, model,
prompt_version, processing_time_ms, raw_response y created_at (ver
AIRecommendation en src/ai/recommendation.py). Los campos de categoría
(recommendation, risk_level, prompt_version) son Enums en el modelo; al
implementar esta clase, deben serializarse a texto (.value) igual que hace
SQLiteAIRepository. 'advantages'/'risks' deben serializarse como JSON
(mismo criterio que SQLiteAIRepository); 'raw_response' es nullable.
"""

from typing import Optional

from src.ai.recommendation import AIRecommendation
from src.ai.repository import AIRepository

_NOT_IMPLEMENTED_MSG = (
    "PostgresAIRepository todavía no está implementado. "
    "Es solo la estructura preparada para una etapa futura de migración "
    "desde SQLite. Ver docs/ARQUITECTURA.md."
)


class PostgresAIRepository(AIRepository):
    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def init(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save(self, recommendation: AIRecommendation) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_latest(self, exchange: str, symbol: str) -> Optional[AIRecommendation]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[AIRecommendation]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
