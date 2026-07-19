"""
Servicio de IA: la lógica de negocio que orquesta la generación de
recomendaciones de la Etapa 4.

Coordina un repositorio de señales (SignalRepository, para leer la última
señal y su historial reciente), un repositorio de indicadores
(IndicatorRepository, para leer los indicadores más recientes), un
repositorio de mercado (MarketDataRepository, para leer el precio actual),
el motor de decisión de IA (DecisionEngine) y un repositorio de IA
(AIRepository, para guardar el resultado). No calcula nada por sí mismo:
delega en DecisionEngine, igual que SignalService delega en SignalEngine.
"""

import logging

from src.ai.context import build_market_context
from src.ai.decision_engine import DecisionEngine
from src.ai.repository import AIRepository
from src.database.base import IndicatorRepository, MarketDataRepository
from src.signals.base import SignalRepository

logger = logging.getLogger(__name__)

# Cuántas señales anteriores (sin contar la última) se incluyen en el
# MarketContext como historial reciente, para que la IA pueda notar cambios
# de tendencia. Es un límite de contexto (cuánto texto entra en el prompt),
# no un umbral de negocio, por eso no está en config.yaml.
_RECENT_SIGNALS_LIMIT = 5


class AIService:
    def __init__(
        self,
        market_repository: MarketDataRepository,
        indicator_repository: IndicatorRepository,
        signal_repository: SignalRepository,
        ai_repository: AIRepository,
        decision_engine: DecisionEngine,
        exchange: str,
        symbols: list[str],
    ):
        self.market_repository = market_repository
        self.indicator_repository = indicator_repository
        self.signal_repository = signal_repository
        self.ai_repository = ai_repository
        self.decision_engine = decision_engine
        self.exchange = exchange
        self.symbols = symbols

    def run_cycle(self) -> None:
        """Genera y guarda la recomendación de IA de cada símbolo
        configurado, a partir de la última señal generada por el motor de
        reglas (Etapa 3) y su historial reciente."""
        logger.info(
            "Iniciando generación de recomendaciones de IA para: %s", ", ".join(self.symbols)
        )

        generated = 0
        for symbol in self.symbols:
            latest_signal = self.signal_repository.fetch_latest(self.exchange, symbol)

            if latest_signal is None:
                logger.warning(
                    "Sin señal disponible todavía para generar una recomendación de IA de %s.",
                    symbol,
                )
                continue

            latest_prices = self.market_repository.fetch_by_symbol(self.exchange, symbol, limit=1)
            current_price = latest_prices[-1].price if latest_prices else None

            if current_price is None:
                logger.warning(
                    "Sin precio disponible todavía para generar una recomendación de IA de %s.",
                    symbol,
                )
                continue

            indicators = self.indicator_repository.fetch_latest(self.exchange, symbol)

            # fetch_history devuelve del más antiguo al más reciente; el
            # último elemento es el mismo que 'latest_signal' (misma fila),
            # así que se excluye para no repetirlo dentro del historial.
            history = self.signal_repository.fetch_history(
                self.exchange, symbol, limit=_RECENT_SIGNALS_LIMIT + 1
            )
            recent_signals = history[:-1] if history else []

            context = build_market_context(
                exchange=self.exchange,
                symbol=symbol,
                current_price=current_price,
                indicators=indicators,
                latest_signal=latest_signal,
                recent_signals=recent_signals,
            )

            recommendation = self.decision_engine.decide(context)
            self.ai_repository.save(recommendation)
            generated += 1

            logger.info(
                "[%s] %s -> recommendation=%s | confidence=%.2f | risk=%s | provider=%s | model=%s",
                recommendation.exchange,
                recommendation.symbol,
                recommendation.recommendation.value,
                recommendation.confidence,
                recommendation.risk_level.value,
                recommendation.provider,
                recommendation.model,
            )

        logger.info(
            "Generación de recomendaciones de IA completada. %d/%d símbolos con recomendación guardada.",
            generated, len(self.symbols),
        )
