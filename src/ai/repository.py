"""
Interfaz común que debe cumplir cualquier repositorio de recomendaciones de IA.

Sigue exactamente el mismo patrón que SignalRepository (src/signals/base.py):
el resto del proyecto (AIService, main.py) no necesita saber si las
recomendaciones se guardan en SQLite, PostgreSQL o cualquier otro motor.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.ai.recommendation import AIRecommendation


class AIRepository(ABC):
    @abstractmethod
    def init(self) -> None:
        """Prepara el almacenamiento (ej. crear tablas) si aún no existe."""

    @abstractmethod
    def save(self, recommendation: AIRecommendation) -> None:
        """Guarda una recomendación generada para un símbolo."""

    @abstractmethod
    def fetch_latest(self, exchange: str, symbol: str) -> Optional[AIRecommendation]:
        """Devuelve la última recomendación guardada para un símbolo de un
        exchange, o None si todavía no hay ninguna."""

    @abstractmethod
    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[AIRecommendation]:
        """Devuelve el historial de recomendaciones de un símbolo, ordenado
        del más antiguo al más reciente."""
