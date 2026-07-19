"""
Contexto de mercado (Etapa 4).

MarketContext agrupa todo lo que el AI Decision Engine necesita para
razonar sobre un símbolo, sin tener que leer nada por su cuenta: el precio
actual, los indicadores técnicos más recientes (Etapa 2), la última señal
generada por el motor de reglas (Etapa 3) y un historial reciente de esas
señales (para que la IA pueda notar cambios de tendencia, no solo el
instante actual).

DecisionEngine SOLO recibe un MarketContext ya armado: no sabe leer de
SQLite ni de Binance (eso es responsabilidad de AIService, que llama a
build_market_context con datos que ya obtuvo de los repositorios
existentes de las Etapas 1.5/2/3).
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot


class MarketContext(BaseModel):
    """Todo lo que el motor de IA necesita saber sobre un símbolo, en un instante."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    current_price: float = Field(gt=0.0)

    indicators: Optional[IndicatorSnapshot] = None
    latest_signal: Optional[SignalSnapshot] = None
    # Del más antiguo al más reciente, igual que SignalRepository.fetch_history.
    # No repite 'latest_signal': es el historial ANTERIOR a ella.
    recent_signals: list[SignalSnapshot] = Field(default_factory=list)

    generated_at: datetime


def build_market_context(
    exchange: str,
    symbol: str,
    current_price: float,
    indicators: Optional[IndicatorSnapshot],
    latest_signal: Optional[SignalSnapshot],
    recent_signals: list[SignalSnapshot],
) -> MarketContext:
    """Arma un MarketContext a partir de datos ya leídos de los repositorios
    existentes. No hace ninguna consulta por sí mismo: solo empaqueta lo que
    AIService ya obtuvo de IndicatorRepository/SignalRepository/MarketDataRepository."""
    return MarketContext(
        exchange=exchange,
        symbol=symbol,
        current_price=current_price,
        indicators=indicators,
        latest_signal=latest_signal,
        recent_signals=recent_signals,
        generated_at=datetime.now(timezone.utc),
    )
