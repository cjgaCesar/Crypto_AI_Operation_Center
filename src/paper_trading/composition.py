"""
Composition Root de Paper Trading (Etapa 6.5).

Única capa autorizada para construir objetos concretos de Paper
Trading: `SQLitePaperTradingRepository`, `PaperTradingService` (con los
5 motores reales, incluyendo `ReservationEngine` desde la Etapa 6.7), y
`PaperTradingApplication`. El resto del proyecto
(main.py) solo debe recibir el `PaperTradingContext` ya construido y
usar `context.application`, sin conocer ninguna clase concreta.

No mantiene conexiones SQLite abiertas ni usa singletons: cada llamada
a `build_paper_trading_context()` construye un repositorio nuevo (que,
como el resto del proyecto, abre una conexión SQLite por operación, ver
sqlite_repository.py) y un `PaperTradingContext` nuevo.

Etapa 6.8: también construye e inyecta `ReconciliationService` (con
`ReconciliationEngine` real), agregado a `PaperTradingContext` como
`reconciliation_service`. Esta función **nunca** llama
`reconciliation_service.inspect()`/`.repair()` durante la construcción
(ver docs/ARQUITECTURA_PAPER_TRADING.md §22.11, Paso 24): el arranque
normal no repara nada, ni siquiera detecta nada -- solo deja el
servicio listo para que la CLI administrativa (u otro caller explícito)
lo invoque.

Etapa 6.9: además construye `InspectionService`/`AlertDeliveryService`/
`InspectionJob` (`inspection_service`/`alert_delivery_service`/
`inspection_job` en `PaperTradingContext`). Tampoco se ejecuta
`run_once()`/entrega alguna durante la construcción (§23.14) -- eso
queda para `inspection_cli.py`/`inspection_scheduler.py`.

Etapa 6.10: `AlertDeliveryService` se construye con un
`CompositeNotificationChannel` (patrón Strategy, ver §24) armado según
`config.paper_trading.inspection_notifications` -- esta función es la
única capa que decide qué canales concretos entran en la lista; ni
`AlertDeliveryService` ni `CompositeNotificationChannel` conocen esos
nombres por separado.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.application import PaperTradingApplication
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.fill_engine import FillEngine
from src.paper_trading.inspection_job import InspectionJob
from src.paper_trading.inspection_service import InspectionService
from src.paper_trading.models import CashBalance
from src.paper_trading.notification_channels import (
    CompositeNotificationChannel, EmailNotificationChannel, InspectionNotificationChannel,
    LoggingNotificationChannel, SlackNotificationChannel, TelegramNotificationChannel,
    WebhookNotificationChannel,
)
from src.paper_trading.pnl_engine import PnLEngine
from src.paper_trading.position_engine import PositionEngine
from src.paper_trading.price_provider import MarketPriceProvider
from src.paper_trading.reconciliation_engine import ReconciliationEngine
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.reservation_engine import ReservationEngine
from src.paper_trading.risk_engine import RiskEngine
from src.paper_trading.runtime import Clock, IdGenerator
from src.paper_trading.service import PaperTradingService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.utils.config import InspectionNotificationsConfig, PaperTradingConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperTradingContext:
    """Contenedor de dependencias ya construidas de Paper Trading."""

    repository: PaperTradingRepository
    service: PaperTradingService
    application: PaperTradingApplication
    config: PaperTradingConfig
    reconciliation_service: ReconciliationService
    inspection_service: InspectionService
    alert_delivery_service: AlertDeliveryService
    inspection_job: InspectionJob


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


def _build_notification_channel(
    config: InspectionNotificationsConfig, clock: Clock,
) -> InspectionNotificationChannel:
    """Único lugar que traduce `inspection_notifications` a una lista de
    canales concretos (§24.5). Agregar un canal nuevo en el futuro es
    agregar una entrada más aquí, nunca una rama dentro de
    AlertDeliveryService/CompositeNotificationChannel."""
    channels: list[InspectionNotificationChannel] = []
    if config.logging:
        channels.append(LoggingNotificationChannel(clock=clock))
    if config.email:
        channels.append(EmailNotificationChannel())
    if config.slack:
        channels.append(SlackNotificationChannel())
    if config.telegram:
        channels.append(TelegramNotificationChannel())
    if config.webhook:
        channels.append(WebhookNotificationChannel())
    return CompositeNotificationChannel(channels, clock=clock)


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
        reservation_engine=ReservationEngine,
    )

    reconciliation_service = ReconciliationService(repository=repository, engine=ReconciliationEngine)

    inspection_service = InspectionService(
        repository=repository, reconciliation_service=reconciliation_service,
        id_generator=id_generator, clock=clock,
    )
    alert_delivery_service = AlertDeliveryService(
        repository=repository,
        channel=_build_notification_channel(config.inspection_notifications, clock),
        max_attempts=config.reconciliation_inspection.max_alert_delivery_attempts,
    )
    inspection_job = InspectionJob(
        inspection_service=inspection_service, alert_delivery_service=alert_delivery_service,
        clock=clock, id_generator=id_generator,
        deliver_alerts=config.reconciliation_inspection.deliver_alerts,
        alert_batch_size=config.reconciliation_inspection.pending_alert_batch_size,
    )

    application = PaperTradingApplication(
        service=service,
        repository=repository,
        price_provider=market_price_provider,
        clock=clock,
        id_generator=id_generator,
        config=config,
        reconciliation_service=reconciliation_service,
        inspection_service=inspection_service,
        alert_delivery_service=alert_delivery_service,
    )

    return PaperTradingContext(
        repository=repository, service=service, application=application, config=config,
        reconciliation_service=reconciliation_service, inspection_service=inspection_service,
        alert_delivery_service=alert_delivery_service, inspection_job=inspection_job,
    )
