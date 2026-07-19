"""
Servicio de indicadores técnicos: la lógica de negocio que orquesta el
cálculo de indicadores de la Etapa 2.

Coordina un repositorio de mercado (MarketDataRepository, para leer el
historial de precios), el motor de cálculo (IndicatorEngine, cálculo puro)
y un repositorio de indicadores (IndicatorRepository, para guardar el
resultado). No calcula nada por sí mismo: delega el cálculo al motor, igual
que MarketDataService delega la consulta de precios al ExchangeClient.
"""

import logging

from src.database.base import IndicatorRepository, MarketDataRepository
from src.services.indicator_engine import IndicatorEngine

logger = logging.getLogger(__name__)


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "N/D"


class IndicatorService:
    def __init__(
        self,
        market_repository: MarketDataRepository,
        indicator_repository: IndicatorRepository,
        engine: IndicatorEngine,
        exchange: str,
        symbols: list[str],
    ):
        self.market_repository = market_repository
        self.indicator_repository = indicator_repository
        self.engine = engine
        self.exchange = exchange
        self.symbols = symbols

    def run_cycle(self) -> None:
        """Recalcula y guarda los indicadores de cada símbolo configurado,
        usando el historial de precios disponible hasta el momento."""
        logger.info("Iniciando cálculo de indicadores para: %s", ", ".join(self.symbols))

        calculated = 0
        for symbol in self.symbols:
            history = self.market_repository.fetch_by_symbol(self.exchange, symbol)
            snapshot = self.engine.calculate(self.exchange, symbol, history)

            if snapshot is None:
                logger.warning(
                    "Sin historial suficiente para calcular indicadores de %s (%d lectura(s) guardada(s)).",
                    symbol, len(history),
                )
                continue

            self.indicator_repository.save(snapshot)
            calculated += 1
            logger.info(
                "[%s] %s -> SMA=%s | EMA(%d/%d/%d)=%s/%s/%s | RSI=%s | "
                "MACD=%s/%s/%s | BB=%s/%s/%s | VWAP=%s",
                snapshot.exchange,
                snapshot.symbol,
                _fmt(snapshot.sma),
                self.engine.settings.ema_fast,
                self.engine.settings.ema_medium,
                self.engine.settings.ema_slow,
                _fmt(snapshot.ema_fast),
                _fmt(snapshot.ema_medium),
                _fmt(snapshot.ema_slow),
                _fmt(snapshot.rsi),
                _fmt(snapshot.macd_line),
                _fmt(snapshot.macd_signal),
                _fmt(snapshot.macd_histogram),
                _fmt(snapshot.bollinger_upper),
                _fmt(snapshot.bollinger_middle),
                _fmt(snapshot.bollinger_lower),
                _fmt(snapshot.vwap),
            )

        logger.info(
            "Cálculo de indicadores completado. %d/%d símbolos con indicadores guardados.",
            calculated, len(self.symbols),
        )
