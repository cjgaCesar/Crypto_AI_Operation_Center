"""
Implementación futura de SignalRepository usando PostgreSQL.

Este archivo NO se usa todavía en ningún lugar del proyecto. Igual que
src/database/postgres_repository.py (para market_data) y
src/database/postgres_indicator_repository.py (para market_indicators), se
deja preparado para cuando se decida migrar de SQLite a PostgreSQL.

La tabla equivalente deberá incluir las mismas columnas que usa hoy
SQLiteSignalRepository: exchange, symbol, trend, trend_strength,
ema_signal, macd_signal, rsi_signal, bollinger_signal, trend_reason,
ema_reason, macd_reason, rsi_reason, bollinger_reason, trend_rule_strength,
ema_rule_strength, macd_rule_strength, rsi_rule_strength,
bollinger_rule_strength, score, confidence, signal_type y generated_at (ver
SignalSnapshot en src/models/signal_data.py). Los campos de categoría
(trend, ema_signal, etc.) son Enums en el modelo; al implementar esta
clase, deben serializarse a texto (.value) igual que hace
SQLiteSignalRepository.
"""

from typing import Optional

from src.signals.base import SignalRepository
from src.models.signal_data import SignalSnapshot

_NOT_IMPLEMENTED_MSG = (
    "PostgresSignalRepository todavía no está implementado. "
    "Es solo la estructura preparada para una etapa futura de migración "
    "desde SQLite. Ver docs/ARQUITECTURA.md."
)


class PostgresSignalRepository(SignalRepository):
    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def init(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save(self, snapshot: SignalSnapshot) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_latest(self, exchange: str, symbol: str) -> Optional[SignalSnapshot]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[SignalSnapshot]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
