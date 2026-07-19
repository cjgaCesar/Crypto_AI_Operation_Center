"""
Modelos de presentación del Dashboard (Etapa 5).

Son modelos Pydantic puros: no abren conexiones SQLite, no ejecutan
consultas, no dependen de Streamlit. Reutilizan por composición los
modelos ya existentes (MarketTicker, IndicatorSnapshot, SignalSnapshot,
AIRecommendation) en vez de duplicar sus campos: cada "Latest*Snapshot"
solo agrega el envoltorio necesario para representar la ausencia de datos
(el campo queda en None cuando todavía no hay ningún registro guardado
para ese símbolo), algo que los modelos originales no necesitan expresar
porque siempre se construyen a partir de una fila real.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.ai.recommendation import AIRecommendation
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot


class TableStatus(BaseModel):
    """Estado técnico de una de las 4 tablas (existe, cuántas filas tiene,
    cuál es el timestamp del registro más reciente)."""

    table_name: str = Field(min_length=1)
    exists: bool
    row_count: int = Field(ge=0, default=0)
    latest_timestamp: Optional[datetime] = None


class DashboardStatus(BaseModel):
    """Estado técnico general: si el archivo SQLite existe y el estado de
    cada una de las 4 tablas. Usado por la página 'Estado Técnico' y para
    decidir qué mostrar cuando la base todavía no existe."""

    database_path: str = Field(min_length=1)
    database_exists: bool
    tables: list[TableStatus] = Field(default_factory=list)


class LatestMarketSnapshot(BaseModel):
    """Último precio guardado para (exchange, symbol), o ninguno si
    todavía no hay datos."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    ticker: Optional[MarketTicker] = None


class LatestIndicatorSnapshot(BaseModel):
    """Último snapshot de indicadores para (exchange, symbol), o ninguno
    si todavía no hay datos."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    indicators: Optional[IndicatorSnapshot] = None


class LatestSignalSnapshot(BaseModel):
    """Última señal generada para (exchange, symbol), o ninguna si
    todavía no hay datos."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    signal: Optional[SignalSnapshot] = None


class LatestAIRecommendationSnapshot(BaseModel):
    """Última recomendación de IA para (exchange, symbol), o ninguna si
    todavía no hay datos."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    recommendation: Optional[AIRecommendation] = None


class DashboardSummary(BaseModel):
    """Resumen de un símbolo: lo último de las 4 tablas en un solo
    objeto, para la página 'Resumen General'. Cada parte puede estar
    vacía de forma independiente (ej. hay precio pero todavía no hay
    señal)."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    market: LatestMarketSnapshot
    indicators: LatestIndicatorSnapshot
    signal: LatestSignalSnapshot
    ai_recommendation: LatestAIRecommendationSnapshot
