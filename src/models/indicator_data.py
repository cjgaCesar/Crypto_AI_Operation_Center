"""
Modelo de datos para representar un conjunto de indicadores técnicos
calculados para un símbolo, en un momento dado.

Todos los indicadores son opcionales (Optional[float]): mientras no haya
suficiente historial de precios todavía (ej. se necesitan al menos
`ema_slow` lecturas para el primer valor de EMA lenta), el campo
correspondiente queda en None en vez de forzar un valor incorrecto.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IndicatorSnapshot(BaseModel):
    """Indicadores técnicos calculados para (exchange, symbol) en un instante."""

    exchange: str
    symbol: str

    sma: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_medium: Optional[float] = None
    ema_slow: Optional[float] = None
    rsi: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None
    vwap: Optional[float] = None

    calculated_at: datetime
