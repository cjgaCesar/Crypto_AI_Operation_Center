"""
Punto de entrada del proyecto (Composition Root).

Este archivo SOLO arma las piezas (configuración, cliente de exchange,
repositorios, servicios) y coordina el ciclo de ejecución. Toda la lógica
de negocio vive en src/services/ y src/signals/, y todo el acceso a datos
externos vive en src/market/ y src/database/ (+ src/signals/ para el
repositorio de señales).

Cada ciclo (cada 'interval_minutes'), en orden:
1. MarketDataService consulta el exchange y guarda los precios crudos
   (market_data).
2. IndicatorService recalcula los indicadores técnicos con el historial
   actualizado y los guarda por separado (market_indicators).
3. SignalService transforma los indicadores más recientes en una señal
   estructurada (sin IA) y la guarda por separado (market_signals).
4. AIService interpreta la última señal con el motor de decisión de IA
   (Etapa 4) y guarda la recomendación por separado (ai_recommendations).
   La IA NO reemplaza al motor de señales: solo lo interpreta, explica y
   prioriza.

Ejecutar con:  python -m src.main
Detener con:   Ctrl + C
"""

import logging
import time
from typing import Optional

import schedule

from src.utils.config import Settings, load_settings
from src.utils.logger import setup_logging
from src.market.binance import BinanceExchangeClient
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.signals.sqlite_repository import SQLiteSignalRepository
from src.services.market_data_service import MarketDataService
from src.services.indicator_engine import IndicatorEngine
from src.services.indicator_service import IndicatorService
from src.signals.engine import SignalEngine
from src.signals.service import SignalService
from src.ai.base import AIProvider
from src.ai.decision_engine import DecisionEngine
from src.ai.prompt_builder import PromptBuilder
from src.ai.providers.claude_provider import ClaudeProvider
from src.ai.providers.dummy_provider import DummyProvider
from src.ai.providers.openai_provider import OpenAIProvider
from src.ai.service import AIService
from src.ai.sqlite_repository import SQLiteAIRepository
from src.paper_trading.composition import PaperTradingContext, build_paper_trading_context
from src.paper_trading.price_provider import RepositoryMarketPriceProvider
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator

logger = logging.getLogger(__name__)


def _build_ai_provider(settings: Settings) -> AIProvider:
    """Instancia el AIProvider activo según settings.ai_engine.provider.

    Este es el único lugar del proyecto que sabe qué proveedor de IA está
    en uso hoy. Cambiar de "dummy" a "openai"/"claude" en config.yaml (una
    vez que esos proveedores estén realmente implementados) no requiere
    tocar DecisionEngine, PromptBuilder ni AIService.
    """
    ai_engine = settings.ai_engine
    if ai_engine.provider == "openai":
        return OpenAIProvider(
            api_key=settings.ai.openai_api_key,
            model=ai_engine.model,
            temperature=ai_engine.temperature,
            max_tokens=ai_engine.max_tokens,
        )
    if ai_engine.provider == "claude":
        return ClaudeProvider(
            api_key=settings.ai.anthropic_api_key,
            model=ai_engine.model,
            temperature=ai_engine.temperature,
            max_tokens=ai_engine.max_tokens,
        )
    return DummyProvider(delay_seconds=ai_engine.dummy_delay)


def build_services(
    settings: Settings,
) -> tuple[MarketDataService, IndicatorService, SignalService, Optional[AIService]]:
    """Arma los servicios de la aplicación a partir de la configuración.

    Hoy siempre se instancia BinanceExchangeClient y los repositorios
    SQLite. Cuando se agreguen más exchanges o PostgreSQL, este es el único
    lugar que tendría que cambiar, ya que el resto del proyecto solo conoce
    las interfaces (ExchangeClient, MarketDataRepository, IndicatorRepository,
    SignalRepository).

    Si settings.ai_engine.enabled es False, el 4to elemento devuelto es
    None: ni AIService, ni DecisionEngine, ni el AIProvider activo se
    instancian (no solo se omite su ejecución), para que desactivar la
    Etapa 4 sea una desactivación real y no solo un 'if' en el ciclo.
    """
    exchange_client = BinanceExchangeClient(
        base_url=settings.binance.base_url,
        timeout_seconds=settings.binance.timeout_seconds,
        api_key=settings.binance.api_key,
        api_secret=settings.binance.api_secret,
    )

    market_repository = SQLiteMarketDataRepository(settings.database.sqlite_path)
    market_repository.init()

    indicator_repository = SQLiteIndicatorRepository(settings.database.sqlite_path)
    indicator_repository.init()

    signal_repository = SQLiteSignalRepository(settings.database.sqlite_path)
    signal_repository.init()

    market_data_service = MarketDataService(
        exchange_client=exchange_client,
        repository=market_repository,
        symbols=settings.symbols,
    )

    indicator_service = IndicatorService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        engine=IndicatorEngine(settings.indicators),
        exchange=exchange_client.exchange_name,
        symbols=settings.symbols,
    )

    signal_service = SignalService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        signal_repository=signal_repository,
        engine=SignalEngine(settings.signals),
        exchange=exchange_client.exchange_name,
        symbols=settings.symbols,
    )

    ai_service: Optional[AIService] = None
    if settings.ai_engine.enabled:
        ai_repository = SQLiteAIRepository(settings.database.sqlite_path)
        ai_repository.init()

        ai_service = AIService(
            market_repository=market_repository,
            indicator_repository=indicator_repository,
            signal_repository=signal_repository,
            ai_repository=ai_repository,
            decision_engine=DecisionEngine(
                provider=_build_ai_provider(settings),
                prompt_builder=PromptBuilder(),
                system_prompt=settings.ai_engine.system_prompt,
            ),
            exchange=exchange_client.exchange_name,
            symbols=settings.symbols,
        )

    return market_data_service, indicator_service, signal_service, ai_service


def build_paper_trading(settings: Settings) -> Optional[PaperTradingContext]:
    """Construye el contexto de Paper Trading (Etapa 6.5) si está habilitado.

    Mismo criterio que build_services() ya usa para settings.ai_engine.enabled:
    si settings.paper_trading.enabled es False, no se instancia absolutamente
    nada (ni siquiera el repositorio) -- una desactivación real, no solo un
    'if' que se salta en el ciclo. El repositorio de mercado que alimenta a
    RepositoryMarketPriceProvider es una instancia propia (no la que usa
    MarketDataService dentro de build_services()), igual que ya sucede entre
    los distintos repositorios SQLite del proyecto: cada uno abre su propia
    conexión por llamada, así que instanciar otro apuntando al mismo archivo
    es seguro.

    El contexto devuelto queda disponible para uso manual/futuro
    (context.application.submit_manual_market_order(...)) -- esta función
    nunca ejecuta ninguna orden por su cuenta.
    """
    if not settings.paper_trading.enabled:
        logger.info("Paper Trading deshabilitado (paper_trading.enabled=false).")
        return None

    market_repository = SQLiteMarketDataRepository(settings.database.sqlite_path)
    market_repository.init()

    return build_paper_trading_context(
        config=settings.paper_trading,
        clock=SystemClock(),
        id_generator=UUIDIdGenerator(),
        market_price_provider=RepositoryMarketPriceProvider(market_repository),
    )


def run_full_cycle(
    market_data_service: MarketDataService,
    indicator_service: IndicatorService,
    signal_service: SignalService,
    ai_service: Optional[AIService],
) -> None:
    """Un ciclo completo: precios -> indicadores -> señales -> IA, en ese
    orden, para que cada etapa use datos ya actualizados por la anterior.

    'ai_service' es None cuando settings.ai_engine.enabled es False (ver
    build_services): en ese caso el paso de IA se omite por completo, sin
    afectar a los 3 pasos anteriores."""
    market_data_service.run_cycle()
    indicator_service.run_cycle()
    signal_service.run_cycle()
    if ai_service is not None:
        ai_service.run_cycle()


def main() -> None:
    settings = load_settings()
    setup_logging(settings.logging.path, settings.logging.level)

    logger.info("=== Crypto AI Operation Center ===")
    logger.info("Monedas configuradas: %s", ", ".join(settings.symbols))
    logger.info("Intervalo de consulta: cada %s minutos", settings.interval_minutes)

    market_data_service, indicator_service, signal_service, ai_service = build_services(settings)

    # Disponible para uso manual/futuro (context.application.submit_manual_market_order()).
    # Ningún ciclo, señal ni recomendación de IA lo invoca todavía (Etapa 6.5).
    paper_trading_context = build_paper_trading(settings)

    # Primera ejecución inmediata, sin esperar el primer intervalo.
    run_full_cycle(market_data_service, indicator_service, signal_service, ai_service)

    schedule.every(settings.interval_minutes).minutes.do(
        run_full_cycle, market_data_service, indicator_service, signal_service, ai_service
    )

    logger.info("Bot en ejecución. Presiona Ctrl+C para detenerlo.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot detenido manualmente por el usuario.")


if __name__ == "__main__":
    main()
