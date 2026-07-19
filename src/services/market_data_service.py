"""
Servicio de datos de mercado: la lógica de negocio de la Etapa 1/1.5.

Coordina un cliente de exchange (ExchangeClient) y un repositorio
(MarketDataRepository) para ejecutar un ciclo completo de consulta y
guardado. No sabe si el exchange es Binance u otro, ni si el repositorio es
SQLite o PostgreSQL: solo conoce las interfaces (src/market/base.py y
src/database/base.py). Esto es lo que permite que main.py quede reducido a
solo "armar piezas y arrancar", sin contener lógica de negocio.
"""

import logging

from src.database.base import MarketDataRepository
from src.market.base import ExchangeClient

logger = logging.getLogger(__name__)


class MarketDataService:
    def __init__(
        self,
        exchange_client: ExchangeClient,
        repository: MarketDataRepository,
        symbols: list[str],
    ):
        self.exchange_client = exchange_client
        self.repository = repository
        self.symbols = symbols

    def run_cycle(self) -> None:
        """Ejecuta una consulta completa: exchange -> validación -> guardado."""
        logger.info("Iniciando ciclo de consulta para: %s", ", ".join(self.symbols))

        tickers = self.exchange_client.get_tickers(self.symbols)

        if not tickers:
            logger.warning("El ciclo no obtuvo ningún dato válido del exchange.")
            return

        self.repository.save(tickers)

        for ticker in tickers:
            logger.info(
                "[%s] %s -> precio=%.4f | volumen_24h=%.4f | variacion_24h=%.2f%% | consultado_en=%s",
                ticker.exchange,
                ticker.symbol,
                ticker.price,
                ticker.volume_24h,
                ticker.price_change_percent_24h,
                ticker.queried_at.isoformat(),
            )

        logger.info(
            "Ciclo completado. %d/%d símbolos guardados.",
            len(tickers),
            len(self.symbols),
        )
