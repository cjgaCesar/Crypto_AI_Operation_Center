"""
Modelo de datos para representar información de mercado de una criptomoneda.

En la Etapa 1 esta información se pasaba como un diccionario simple. Usar un
modelo de Pydantic en su lugar da dos beneficios concretos:

1. Validación automática: si un exchange devuelve un dato en un formato
   inesperado (ej. un precio que no es un número), el error se detecta aquí,
   de forma clara, en lugar de propagarse silenciosamente al resto del
   sistema (base de datos, servicios de IA, dashboard, etc.).
2. Autocompletado y chequeo de tipos en el resto del código: en vez de
   escribir ticker["price"] (que puede fallar si se escribe mal la clave),
   se escribe ticker.price.
"""

from datetime import datetime

from pydantic import BaseModel


class MarketTicker(BaseModel):
    """Resultado de una consulta de mercado para un símbolo (ej. BTCUSDT).

    El campo 'exchange' identifica de qué exchange vino el dato. Hoy solo
    existe la implementación de Binance, por lo que su valor por defecto es
    "Binance"; cuando se agreguen otros exchanges (Bybit, Coinbase, Kraken),
    cada uno deberá indicar su propio nombre explícitamente.
    """

    exchange: str = "Binance"
    symbol: str
    price: float
    volume_24h: float
    price_change_percent_24h: float
    queried_at: datetime
