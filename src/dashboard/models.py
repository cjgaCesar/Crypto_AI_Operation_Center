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

from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.enums import ConfidenceLevel, SignalType


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


class DashboardSummaryView(BaseModel):
    """Vista aplanada de un símbolo para la página 'Resumen General'.

    A diferencia de DashboardSummary (que anida los 4 modelos completos),
    esta vista expone directamente los campos puntuales que la tarjeta de
    resumen necesita mostrar (precio, señal, recomendación de IA...), para
    que la página no tenga que navegar 'summary.signal.signal.score' —
    pero sin duplicar los modelos de dominio: los tipos de cada campo
    (SignalType, ConfidenceLevel, RecommendationAction, RiskLevel) son los
    mismos Enums que ya usan SignalSnapshot/AIRecommendation, no copias.

    Todos los campos que dependen de una tabla que puede no tener datos
    todavía son Optional (None = "todavía no hay ese dato"), y los 4
    'has_*_data' dejan explícito qué tabla sí/no tiene datos, sin que la
    página deba inferirlo revisando si un campo es None."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)

    price: Optional[float] = None
    price_change_percent_24h: Optional[float] = None
    market_timestamp: Optional[datetime] = None

    signal_type: Optional[SignalType] = None
    signal_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    signal_confidence: Optional[ConfidenceLevel] = None
    signal_timestamp: Optional[datetime] = None

    ai_recommendation: Optional[RecommendationAction] = None
    ai_confidence: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    ai_risk_level: Optional[RiskLevel] = None
    ai_timestamp: Optional[datetime] = None

    latest_update_timestamp: Optional[datetime] = None

    has_market_data: bool = False
    has_indicator_data: bool = False
    has_signal_data: bool = False
    has_ai_data: bool = False
