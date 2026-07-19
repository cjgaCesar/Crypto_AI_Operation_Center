"""
Interfaz común que debe cumplir cualquier repositorio de señales.

Sigue exactamente el mismo patrón que MarketDataRepository e
IndicatorRepository (src/database/base.py): el resto del proyecto
(SignalService, main.py) no necesita saber si las señales se guardan en
SQLite, PostgreSQL o cualquier otro motor.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.models.signal_data import SignalSnapshot


class SignalRepository(ABC):
    @abstractmethod
    def init(self) -> None:
        """Prepara el almacenamiento (ej. crear tablas) si aún no existe."""

    @abstractmethod
    def save(self, snapshot: SignalSnapshot) -> None:
        """Guarda una señal generada para un símbolo."""

    @abstractmethod
    def fetch_latest(self, exchange: str, symbol: str) -> Optional[SignalSnapshot]:
        """Devuelve la última señal guardada para un símbolo de un exchange,
        o None si todavía no hay ninguna."""

    @abstractmethod
    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[SignalSnapshot]:
        """Devuelve el historial de señales de un símbolo, ordenado del más
        antiguo al más reciente."""
