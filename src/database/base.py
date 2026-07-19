"""
Interfaz común que debe cumplir cualquier repositorio de datos de mercado.

Gracias a esta interfaz, el resto del proyecto (servicios, main.py) no
necesita saber si los datos se guardan en SQLite, PostgreSQL o cualquier
otro motor: solo necesita saber que el repositorio sabe hacer init(),
save() y fetch_all().
"""

from abc import ABC, abstractmethod

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
