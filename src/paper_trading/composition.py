"""
Composition Root de Paper Trading (Etapa 6.5).

Única capa autorizada para construir objetos concretos de Paper
Trading: `SQLitePaperTradingRepository`, `PaperTradingService` (con los
4 motores reales), y `PaperTradingApplication`. El resto del proyecto
(main.py) solo debe recibir el `PaperTradingContext` ya construido y
usar `context.application`, sin conocer ninguna clase concreta.

No mantiene conexiones SQLite abiertas ni usa singletons: cada llamada
a `build_paper_trading_context()` construye un repositorio nuevo (que,
como el resto del proyecto, abre una conexión SQLite por operación, ver
sqlite_repository.py) y un `PaperTradingContext` nuevo.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.paper_trading.application import PaperTradingApplication
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.fill_engine import FillEngine
from src.paper_trading.models import CashBalance
from src.paper_trading.pnl_engine import PnLEngine
from src.paper_trading.position_engine import PositionEngine
from src.paper_trading.price_provider import MarketPriceProvider
from src.paper_trading.risk_engine import RiskEngine
from src.paper_trading.runtime import Clock, IdGenerator
from src.paper_trading.service import PaperTradingService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.utils.config import PaperTradingConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperTradingContext:
    """Contenedor de dependencias ya construidas de Paper Trading."""

    repository: PaperTradingRepository
    service: PaperTradingService
    application: PaperTradingApplication
    config: PaperTradingConfig


def seed_initial_cash_balance(
    repository: PaperTradingRepository,
    initial_capital: Decimal,
    currency: str,
    timestamp: datetime,
) -> CashBalance:
    """Siembra el capital inicial de la cuenta de Paper Trading, una sola vez.

    Idempotente: si ya existe un `CashBalance` para `currency`, se
    devuelve tal cual (nunca se sobrescribe, ni se resetea, ni se suma
    `initial_capital` de nuevo). `timestamp` se recibe como argumento
    (nunca `datetime.now()` interno) para que la Composition Root siga
    la misma regla de pureza que los motores (Etapa 6.2, Paso 8).
    """
    if initial_capital <= Decimal("0"):
        raise ValueError("initial_capital debe ser mayor a 0.")

    existing = repository.get_cash_balance(currency)
    if existing is not None:
        logger.info("Capital de Paper Trading ya existente preservado (currency=%s).", currency)
        return existing

    cash_balance = CashBalance(
        currency=currency, total_balance=initial_capital, reserved_balance=Decimal("0"),
        updated_at=timestamp,
    )
    repository.save_cash_balance(cash_balance)
    logger.info("Capital inicial de Paper Trading creado (currency=%s).", currency)
    return cash_balance


def build_paper_trading_context(
    config: PaperTradingConfig,
    clock: Clock,
    id_generator: IdGenerator,
    market_price_provider: MarketPriceProvider,
) -> PaperTradingContext:
    """Construye el repositorio, el servicio y la aplicación de Paper Trading.

    Se puede llamar más de una vez sobre la misma base de datos sin
    efectos destructivos: `repository.init()` es idempotente (Etapa 6.3)
    y `seed_initial_cash_balance()` nunca duplica ni reinicia el saldo.
    """
    logger.info("Paper Trading %s.", "habilitado" if config.enabled else "deshabilitado")

    repository = SQLitePaperTradingRepository(config.database_path)
    repository.init()
    logger.info("Repositorio de Paper Trading inicializado (database_path=%s).", config.database_path)

    seed_initial_cash_balance(
        repository=repository,
        initial_capital=config.initial_capital,
        currency=config.currency,
        timestamp=clock.now(),
    )

    service = PaperTradingService(
        repository=repository,
        fill_engine=FillEngine,
        position_engine=PositionEngine,
        pnl_engine=PnLEngine,
        risk_engine=RiskEngine,
    )

    application = PaperTradingApplication(
        service=service,
        repository=repository,
        price_provider=market_price_provider,
        clock=clock,
        id_generator=id_generator,
        config=config,
    )

    return PaperTradingContext(
        repository=repository, service=service, application=application, config=config,
    )
