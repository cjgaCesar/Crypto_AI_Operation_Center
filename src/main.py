"""
Punto de entrada del proyecto.

Este archivo SOLO arma las piezas (configuración, cliente de exchange,
repositorio, servicio) y coordina el ciclo de ejecución. Toda la lógica de
negocio vive en src/services/market_data_service.py, y toda la lógica de
acceso a datos externos vive en src/market/ y src/database/.

Ejecutar con:  python -m src.main
Detener con:   Ctrl + C
"""

import logging
import time

import schedule

from src.utils.config import Settings, load_settings
from src.utils.logger import setup_logging
from src.market.binance import BinanceExchangeClient
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)


def build_service(settings: Settings) -> MarketDataService:
    """Arma el servicio de datos de mercado a partir de la configuración.

    Hoy siempre se instancia BinanceExchangeClient y SQLiteMarketDataRepository.
    Cuando se agreguen más exchanges o PostgreSQL, este es el único lugar que
    tendría que cambiar (ej. elegir la clase según settings), ya que el
    resto del proyecto solo conoce las interfaces ExchangeClient y
    MarketDataRepository.
    """
    exchange_client = BinanceExchangeClient(
        base_url=settings.binance.base_url,
        timeout_seconds=settings.binance.timeout_seconds,
        api_key=settings.binance.api_key,
        api_secret=settings.binance.api_secret,
    )

    repository = SQLiteMarketDataRepository(settings.database.sqlite_path)
    repository.init()

    return MarketDataService(
        exchange_client=exchange_client,
        repository=repository,
        symbols=settings.symbols,
    )


def main() -> None:
    settings = load_settings()
    setup_logging(settings.logging.path, settings.logging.level)

    logger.info("=== Crypto AI Operation Center ===")
    logger.info("Monedas configuradas: %s", ", ".join(settings.symbols))
    logger.info("Intervalo de consulta: cada %s minutos", settings.interval_minutes)

    service = build_service(settings)

    # Primera ejecución inmediata, sin esperar el primer intervalo.
    service.run_cycle()

    schedule.every(settings.interval_minutes).minutes.do(service.run_cycle)

    logger.info("Bot en ejecución. Presiona Ctrl+C para detenerlo.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot detenido manualmente por el usuario.")


if __name__ == "__main__":
    main()
