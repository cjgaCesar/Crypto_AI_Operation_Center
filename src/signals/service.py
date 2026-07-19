"""
Servicio de señales: la lógica de negocio que orquesta la generación de
señales de la Etapa 3.

Coordina un repositorio de indicadores (IndicatorRepository, para leer el
último snapshot calculado), un repositorio de mercado (MarketDataRepository,
para leer el precio actual), el motor de señales (SignalEngine, cálculo
puro) y un repositorio de señales (SignalRepository, para guardar el
resultado). No calcula nada por sí mismo: delega el cálculo al motor, igual
que IndicatorService delega en IndicatorEngine.
"""

import logging

from src.database.base import IndicatorRepository, MarketDataRepository
from src.signals.base import SignalRepository
from src.signals.engine import SignalEngine

logger = logging.getLogger(__name__)


class SignalService:
    def __init__(
        self,
        market_repository: MarketDataRepository,
        indicator_repository: IndicatorRepository,
        signal_repository: SignalRepository,
        engine: SignalEngine,
        exchange: str,
        symbols: list[str],
    ):
        self.market_repository = market_repository
        self.indicator_repository = indicator_repository
        self.signal_repository = signal_repository
        self.engine = engine
        self.exchange = exchange
        self.symbols = symbols

    def run_cycle(self) -> None:
        """Genera y guarda la señal de cada símbolo configurado, a partir
        del último indicador calculado y el último precio guardado."""
        logger.info("Iniciando generación de señales para: %s", ", ".join(self.symbols))

        generated = 0
        for symbol in self.symbols:
            indicators = self.indicator_repository.fetch_latest(self.exchange, symbol)

            latest_prices = self.market_repository.fetch_by_symbol(
                self.exchange, symbol, limit=1
            )
            current_price = latest_prices[-1].price if latest_prices else None

            signal = self.engine.calculate(self.exchange, symbol, indicators, current_price)

            if signal is None:
                logger.warning(
                    "Sin indicadores o precio disponibles todavía para generar señal de %s.",
                    symbol,
                )
                continue

            self.signal_repository.save(signal)
            generated += 1
            # .value explícito: los campos de categoría son Enums (no str
            # sueltos); .value garantiza el texto legible en el log sin
            # depender de cómo Enum.__str__/__format__ se comporte según
            # la versión de Python.
            logger.info(
                "[%s] %s -> trend=%s (%s) | EMA=%s (%.2f) | MACD=%s (%.2f) | "
                "RSI=%s (%.2f) | BB=%s (%.2f) | score=%.2f | confidence=%s | signal_type=%s",
                signal.exchange,
                signal.symbol,
                signal.trend.value,
                signal.trend_strength.value,
                signal.ema_signal.value,
                signal.ema_rule_strength,
                signal.macd_signal.value,
                signal.macd_rule_strength,
                signal.rsi_signal.value,
                signal.rsi_rule_strength,
                signal.bollinger_signal.value,
                signal.bollinger_rule_strength,
                signal.score,
                signal.confidence.value,
                signal.signal_type.value,
            )

        logger.info(
            "Generación de señales completada. %d/%d símbolos con señal guardada.",
            generated, len(self.symbols),
        )
