"""
Implementación futura de IndicatorRepository usando PostgreSQL.

Este archivo NO se usa todavía en ningún lugar del proyecto. Igual que
src/database/postgres_repository.py (para market_data), se deja preparado
para cuando se decida migrar de SQLite a PostgreSQL.

La tabla equivalente deberá incluir las mismas columnas que usa hoy
SQLiteIndicatorRepository: exchange, symbol, sma, ema_fast, ema_medium,
ema_slow, rsi, macd_line, macd_signal, macd_histogram, bollinger_upper,
bollinger_middle, bollinger_lower, vwap y calculated_at (ver
IndicatorSnapshot en src/models/indicator_data.py).
"""

from typing import Optional

from src.database.base import IndicatorRepository
from src.models.indicator_data import IndicatorSnapshot

_NOT_IMPLEMENTED_MSG = (
    "PostgresIndicatorRepository todavía no está implementado. "
    "Es solo la estructura preparada para una etapa futura de migración "
    "desde SQLite. Ver docs/ARQUITECTURA.md."
)


class PostgresIndicatorRepository(IndicatorRepository):
    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def init(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save(self, snapshot: IndicatorSnapshot) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_latest(self, exchange: str, symbol: str) -> Optional[IndicatorSnapshot]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[IndicatorSnapshot]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
