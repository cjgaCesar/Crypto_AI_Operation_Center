"""
Interfaces comunes que debe cumplir cualquier repositorio de este proyecto.

Gracias a estas interfaces, el resto del proyecto (servicios, main.py) no
necesita saber si los datos se guardan en SQLite, PostgreSQL o cualquier
otro motor: solo necesita conocer estos contratos.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker


class MarketDataRepository(ABC):
    @abstractmethod
    def init(self) -> None:
        """Prepara el almacenamiento (ej. crear tablas) si aún no existe."""

    @abstractmethod
    def save(self, tickers: list[MarketTicker]) -> None:
        """Guarda una lista de tickers consultados."""

    @abstractmethod
    def fetch_all(self) -> list[MarketTicker]:
        """Devuelve todos los tickers guardados, en orden de inserción."""

    @abstractmethod
    def fetch_by_symbol(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[MarketTicker]:
        """Devuelve el historial de un símbolo de un exchange puntual,
        ordenado del más antiguo al más reciente (usado por el motor de
        indicadores para calcular sobre la serie de precios de cada símbolo).

        Si se indica 'limit', devuelve como máximo esa cantidad de lecturas
        más recientes (igualmente ordenadas de más antigua a más reciente).
        """


class IndicatorRepository(ABC):
    @abstractmethod
    def init(self) -> None:
        """Prepara el almacenamiento (ej. crear tablas) si aún no existe."""

    @abstractmethod
    def save(self, snapshot: IndicatorSnapshot) -> None:
        """Guarda un conjunto de indicadores calculados para un símbolo."""

    @abstractmethod
    def fetch_latest(self, exchange: str, symbol: str) -> Optional[IndicatorSnapshot]:
        """Devuelve el último conjunto de indicadores guardado para un
        símbolo de un exchange, o None si todavía no hay ninguno."""

    @abstractmethod
    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[IndicatorSnapshot]:
        """Devuelve el historial de indicadores de un símbolo, ordenado del
        más antiguo al más reciente."""
