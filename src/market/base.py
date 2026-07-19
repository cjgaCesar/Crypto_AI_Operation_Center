"""
Interfaz común que debe cumplir cualquier cliente de exchange.

El resto del proyecto (servicios, main.py) trabaja contra esta interfaz,
no contra Binance directamente. Esto permite agregar otros exchanges en el
futuro (Bybit, Coinbase, Kraken, etc.) implementando esta misma clase, sin
tener que modificar nada fuera de src/market/.
"""

from abc import ABC, abstractmethod

from src.models.market_data import MarketTicker


class ExchangeClientError(Exception):
    """Error genérico al consultar un exchange (de red, de datos, etc.)."""


class ExchangeClient(ABC):
    """Contrato que debe cumplir cualquier cliente de exchange soportado."""

    #: Nombre del exchange (ej. "Binance", "Bybit"). Cada implementación
    #: concreta debe definirlo, para que los MarketTicker que produce queden
    #: correctamente identificados.
    exchange_name: str

    @abstractmethod
    def get_tickers(self, symbols: list[str]) -> list[MarketTicker]:
        """Consulta el estado actual de una lista de símbolos.

        Debe devolver solo los símbolos consultados con éxito; si alguno
        falla, se registra el error y se omite, para no detener el resto
        del ciclo de consulta.
        """
