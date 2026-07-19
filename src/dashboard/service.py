"""
Servicio del Dashboard (Etapa 5).

Coordina el DashboardRepository (solo lectura) y arma los modelos de
presentación (src/dashboard/models.py) que las páginas necesitan. Sigue el
mismo patrón que los servicios de las Etapas 1 a 4 (ej. SignalService):
recibe sus dependencias por constructor, no ejecuta SQL directamente, y no
sabe nada de cómo se dibuja lo que devuelve.

DashboardService NO:
- ejecuta SQL (delega todo en DashboardRepository),
- crea gráficos (eso vive en src/dashboard/charts.py),
- escribe en SQLite,
- recalcula indicadores,
- genera señales,
- llama a DecisionEngine,
- llama a Binance.

Toda llamada al repositorio pasa por _safe_call()/_safe_list_call(): si el
repositorio lanza una excepción inesperada (más allá de los None/[] que ya
maneja SQLiteDashboardRepository para base/tabla inexistente), el Service
la atrapa y devuelve un resultado vacío en vez de romper la página que lo
llamó — el mismo criterio de "nunca romperse por ausencia de datos",
extendido a errores inesperados del repositorio.
"""

import logging
from typing import Callable, Optional, TypeVar

from src.ai.recommendation import AIRecommendation
from src.dashboard.filters import normalize_exchange, normalize_symbol, validate_limit
from src.dashboard.models import (
    DashboardStatus,
    DashboardSummary,
    DashboardSummaryView,
    LatestAIRecommendationSnapshot,
    LatestIndicatorSnapshot,
    LatestMarketSnapshot,
    LatestSignalSnapshot,
)
from src.dashboard.repository import DashboardRepository
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DashboardService:
    def __init__(
        self,
        repository: DashboardRepository,
        exchange: str,
        symbols: list[str],
        default_history_limit: int,
        max_history_limit: int,
    ):
        self.repository = repository
        self.exchange = exchange
        self.symbols = symbols
        self.default_history_limit = default_history_limit
        self.max_history_limit = max_history_limit

    def get_system_status(self) -> DashboardStatus:
        """Estado técnico del archivo SQLite y de las 4 tablas."""
        return self._safe_call(
            self.repository.get_table_status,
            fallback=DashboardStatus(database_path="(no disponible)", database_exists=False, tables=[]),
        )

    def get_summary(self, exchange: Optional[str] = None) -> list[DashboardSummary]:
        """Un DashboardSummary por cada símbolo configurado
        (settings.symbols), para la página 'Resumen General'."""
        resolved_exchange = normalize_exchange(exchange or self.exchange)
        return [self.get_symbol_summary(resolved_exchange, symbol) for symbol in self.symbols]

    def get_symbol_summary(self, exchange: str, symbol: str) -> DashboardSummary:
        """Último dato de las 4 tablas para un símbolo, cada uno
        independiente (puede haber precio sin que exista todavía señal o
        recomendación de IA)."""
        exchange = normalize_exchange(exchange)
        symbol = normalize_symbol(symbol)

        return DashboardSummary(
            exchange=exchange,
            symbol=symbol,
            market=LatestMarketSnapshot(
                exchange=exchange, symbol=symbol,
                ticker=self._safe_call(lambda: self.repository.get_latest_market(exchange, symbol)),
            ),
            indicators=LatestIndicatorSnapshot(
                exchange=exchange, symbol=symbol,
                indicators=self._safe_call(
                    lambda: self.repository.get_latest_indicators(exchange, symbol)
                ),
            ),
            signal=LatestSignalSnapshot(
                exchange=exchange, symbol=symbol,
                signal=self._safe_call(lambda: self.repository.get_latest_signal(exchange, symbol)),
            ),
            ai_recommendation=LatestAIRecommendationSnapshot(
                exchange=exchange, symbol=symbol,
                recommendation=self._safe_call(
                    lambda: self.repository.get_latest_ai_recommendation(exchange, symbol)
                ),
            ),
        )

    def get_summary_view(self, exchange: Optional[str] = None) -> list[DashboardSummaryView]:
        """Vista aplanada de get_summary(), una por símbolo configurado,
        lista para la página 'Resumen General'. Reutiliza get_summary()
        tal cual (mismas 4 llamadas al repositorio por símbolo, ninguna
        adicional): solo transforma lo ya obtenido, sin volver a
        consultar nada ni recalcular indicadores/señales/IA."""
        return [self._to_summary_view(summary) for summary in self.get_summary(exchange=exchange)]

    @staticmethod
    def _to_summary_view(summary: DashboardSummary) -> DashboardSummaryView:
        ticker = summary.market.ticker
        indicators = summary.indicators.indicators
        signal = summary.signal.signal
        recommendation = summary.ai_recommendation.recommendation

        market_timestamp = ticker.queried_at if ticker else None
        indicator_timestamp = indicators.calculated_at if indicators else None
        signal_timestamp = signal.generated_at if signal else None
        ai_timestamp = recommendation.timestamp if recommendation else None

        timestamps = [
            t for t in (market_timestamp, indicator_timestamp, signal_timestamp, ai_timestamp)
            if t is not None
        ]
        latest_update_timestamp = max(timestamps) if timestamps else None

        return DashboardSummaryView(
            exchange=summary.exchange,
            symbol=summary.symbol,
            price=ticker.price if ticker else None,
            price_change_percent_24h=ticker.price_change_percent_24h if ticker else None,
            market_timestamp=market_timestamp,
            signal_type=signal.signal_type if signal else None,
            signal_score=signal.score if signal else None,
            signal_confidence=signal.confidence if signal else None,
            signal_timestamp=signal_timestamp,
            ai_recommendation=recommendation.recommendation if recommendation else None,
            ai_confidence=recommendation.confidence if recommendation else None,
            ai_risk_level=recommendation.risk_level if recommendation else None,
            ai_timestamp=ai_timestamp,
            latest_update_timestamp=latest_update_timestamp,
            has_market_data=ticker is not None,
            has_indicator_data=indicators is not None,
            has_signal_data=signal is not None,
            has_ai_data=recommendation is not None,
        )

    def get_market_view(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[MarketTicker]:
        exchange, symbol, limit = self._resolve(exchange, symbol, limit)
        return self._safe_call(
            lambda: self.repository.get_market_history(exchange, symbol, limit), fallback=[],
        )

    def get_indicators_view(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[IndicatorSnapshot]:
        exchange, symbol, limit = self._resolve(exchange, symbol, limit)
        return self._safe_call(
            lambda: self.repository.get_indicator_history(exchange, symbol, limit), fallback=[],
        )

    def get_signals_view(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[SignalSnapshot]:
        exchange, symbol, limit = self._resolve(exchange, symbol, limit)
        return self._safe_call(
            lambda: self.repository.get_signal_history(exchange, symbol, limit), fallback=[],
        )

    def get_ai_view(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[AIRecommendation]:
        exchange, symbol, limit = self._resolve(exchange, symbol, limit)
        return self._safe_call(
            lambda: self.repository.get_ai_history(exchange, symbol, limit), fallback=[],
        )

    def _resolve(
        self, exchange: str, symbol: str, limit: Optional[int]
    ) -> tuple[str, str, int]:
        resolved_limit = validate_limit(
            limit, default=self.default_history_limit, maximum=self.max_history_limit,
        )
        return normalize_exchange(exchange), normalize_symbol(symbol), resolved_limit

    @staticmethod
    def _safe_call(func: Callable[[], T], fallback: Optional[T] = None) -> Optional[T]:
        """Ejecuta una llamada al repositorio; si lanza cualquier
        excepción inesperada, la registra en el log y devuelve 'fallback'
        en vez de propagarla (para que la página nunca se rompa)."""
        try:
            return func()
        except Exception:
            logger.warning("DashboardRepository lanzó una excepción inesperada.", exc_info=True)
            return fallback
