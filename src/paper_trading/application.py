"""
PaperTradingApplication -- casos de uso de aplicación para Paper Trading
(Etapa 6.5, ampliado en 6.7 con el ciclo explícito aceptar/llenar/cancelar
y en 6.8 con reconciliación administrativa).

No es lógica de negocio (eso vive en los motores, Etapa 6.2, orquestada
por PaperTradingService, Etapas 6.4/6.7): esta capa solo traduce una
solicitud manual en los argumentos explícitos que el Service necesita --
timestamp (`Clock`), IDs (`IdGenerator`), precio actual
(`MarketPriceProvider`) -- y devuelve el resultado exactamente como lo
produjo el servicio, sin modificarlo.

No calcula riesgo, fees, PnL ni CashBalance; no actualiza `Position`;
no persiste nada por su cuenta; no abre conexiones sqlite3 (todo el
acceso a datos pasa por `PaperTradingRepository`/`PaperTradingService`,
ya inyectados).

`inspect_reconciliation()`/`repair_reconciliation()` (Etapa 6.8) delegan
a `ReconciliationService`: no calculan ningún hallazgo por sí mismos, no
consultan `MarketPriceProvider`, no generan `order_id`/`execution_id`/
`trade_id`, y no llaman a `accept_market_order`/`fill_pending_order`/
`cancel_pending_order` -- ver docs/ARQUITECTURA_PAPER_TRADING.md §22.
"""

import logging
from decimal import Decimal
from typing import Optional

from src.paper_trading.alert_delivery_service import AlertDeliveryBatchResult, AlertDeliveryService
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.inspection_service import InspectionService
from src.paper_trading.models import Order
from src.paper_trading.notification_channels import NullNotificationChannel
from src.paper_trading.price_provider import MarketPriceProvider
from src.paper_trading.reconciliation_models import IssueCode, ReconciliationReport, ReconciliationRepairResult
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.runtime import Clock, IdGenerator
from src.paper_trading.service import PaperTradingService
from src.paper_trading.service_results import (
    AcceptOrderResult, CancelOrderResult, FillPendingOrderResult, SubmitOrderResult,
)
from src.utils.config import PaperTradingConfig

logger = logging.getLogger(__name__)


class PaperTradingDisabledError(Exception):
    """Se intentó invocar un caso de uso de Paper Trading con `paper_trading.enabled=False`.

    No es un rechazo de riesgo (eso ya lo representa
    `RiskValidationResult.approved=False`, ver service_results.py): es
    un error de disponibilidad del caso de uso completo, por eso vive
    en application.py y no en `src/paper_trading/exceptions.py` (que
    pertenece al dominio, no a la capa de aplicación).
    """


class PaperTradingApplication:
    """Expone los casos de uso manuales de Paper Trading (Etapas 6.5/6.7).

    Construida siempre por la Composition Root
    (`src/paper_trading/composition.py`); ningún otro módulo del
    proyecto debe instanciarla directamente.
    """

    def __init__(
        self,
        service: PaperTradingService,
        repository: PaperTradingRepository,
        price_provider: MarketPriceProvider,
        clock: Clock,
        id_generator: IdGenerator,
        config: PaperTradingConfig,
        reconciliation_service: Optional[ReconciliationService] = None,
        inspection_service: Optional[InspectionService] = None,
        alert_delivery_service: Optional[AlertDeliveryService] = None,
    ):
        self._service = service
        self._repository = repository
        self._price_provider = price_provider
        self._clock = clock
        self._id_generator = id_generator
        self._config = config
        self._reconciliation_service = reconciliation_service or ReconciliationService(repository=repository)
        self._inspection_service = inspection_service or InspectionService(
            repository=repository, reconciliation_service=self._reconciliation_service,
            id_generator=id_generator, clock=clock,
        )
        self._alert_delivery_service = alert_delivery_service or AlertDeliveryService(
            repository=repository, channel=NullNotificationChannel(clock=clock),
            max_attempts=config.reconciliation_inspection.max_alert_delivery_attempts,
        )

    def _require_enabled(self, action_description: str) -> None:
        if not self._config.enabled:
            logger.info("Orden manual de Paper Trading rechazada: Paper Trading está deshabilitado (%s).", action_description)
            raise PaperTradingDisabledError(
                "Paper Trading está deshabilitado (paper_trading.enabled=false)."
            )

    @staticmethod
    def _validate_new_order_input(exchange: str, symbol: str, side: OrderSide, quantity: Decimal) -> None:
        if not exchange:
            raise ValueError("exchange no puede estar vacío.")
        if not symbol:
            raise ValueError("symbol no puede estar vacío.")
        if not isinstance(side, OrderSide):
            raise ValueError(f"side debe ser OrderSide.BUY o OrderSide.SELL; se recibió {side!r}.")
        if quantity <= Decimal("0"):
            raise ValueError("quantity debe ser mayor que 0.")

    def _current_prices_for(self, symbol_key: tuple[str, str]) -> dict[tuple[str, str], Decimal]:
        """Precios de `symbol_key` + todas las posiciones abiertas no-FLAT
        (nunca se inventa un precio faltante) -- usado por
        accept_manual_market_order()/submit_manual_market_order(), que sí
        necesitan un precio de mercado nuevo."""
        open_positions = self._repository.fetch_positions(include_flat=False)
        price_keys = {(position.exchange, position.symbol) for position in open_positions}
        price_keys.add(symbol_key)
        return self._price_provider.get_current_prices(list(price_keys))

    # --- Ciclo explícito: aceptar / llenar / cancelar (Etapa 6.7) ----------

    def accept_manual_market_order(
        self,
        exchange: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        source: OrderSource = OrderSource.MANUAL,
        linked_recommendation_id: Optional[str] = None,
    ) -> AcceptOrderResult:
        """Valida riesgo y, si se aprueba, reserva recursos y deja la
        orden en PENDING (sin llenarla). Lanza `PaperTradingDisabledError`
        de inmediato si `paper_trading.enabled` es False, antes de
        consultar precios, generar IDs o construir la `Order`.
        """
        self._require_enabled("accept_manual_market_order")
        self._validate_new_order_input(exchange, symbol, side, quantity)

        try:
            timestamp = self._clock.now()
            symbol_key = (exchange, symbol)
            current_prices = self._current_prices_for(symbol_key)
            market_price = current_prices[symbol_key]

            order = Order(
                id=self._id_generator.new_order_id(),
                exchange=exchange,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                status=OrderStatus.NEW,
                source=source,
                linked_recommendation_id=linked_recommendation_id,
                created_at=timestamp,
                updated_at=timestamp,
            )

            result = self._service.accept_market_order(
                order=order,
                market_price=market_price,
                fee_rate=self._config.fee_rate,
                timestamp=timestamp,
                max_order_value=self._config.max_order_value,
                max_position_value=self._config.max_position_value,
                rules_version=self._config.rules_version,
                currency=self._config.currency,
            )
        except Exception:
            logger.exception("Excepción estructural al aceptar una orden manual de Paper Trading.")
            raise

        if result.success:
            logger.info("Orden manual de Paper Trading aceptada (PENDING): %s %s %s.", side.value, quantity, symbol)
        else:
            logger.info(
                "Orden manual de Paper Trading rechazada por riesgo al aceptar: %s (%s).",
                result.risk_result.code, symbol,
            )
        return result

    def fill_manual_pending_order(self, order_id: str) -> FillPendingOrderResult:
        """Llena una orden PENDING previamente aceptada.

        Usa siempre el precio ya reservado al aceptar (política "MARKET
        se llena al precio aceptado", ver ARQUITECTURA_PAPER_TRADING.md
        §21.3): no vuelve a consultar `MarketPriceProvider` para el
        símbolo operado. Sí consulta precios de OTRAS posiciones
        abiertas, si existen, porque el snapshot de cartera los necesita.
        """
        self._require_enabled("fill_manual_pending_order")

        try:
            order = self._repository.get_order(order_id)
            if order is None:
                raise ValueError(f"No existe una orden con id {order_id}.")

            timestamp = self._clock.now()

            symbol_key = (order.exchange, order.symbol)
            open_positions = self._repository.fetch_positions(include_flat=False)
            other_keys = [
                (position.exchange, position.symbol) for position in open_positions
                if (position.exchange, position.symbol) != symbol_key
            ]
            current_prices = self._price_provider.get_current_prices(other_keys) if other_keys else {}

            # Solo una SELL puede generar un Trade (ver PositionEngine);
            # una BUY nunca lo necesita, así que no se genera un id de más.
            trade_id = self._id_generator.new_trade_id() if order.side == OrderSide.SELL else None

            result = self._service.fill_pending_order(
                order_id=order_id,
                execution_id=self._id_generator.new_execution_id(),
                fee_rate=self._config.fee_rate,
                timestamp=timestamp,
                trade_id=trade_id,
                currency=self._config.currency,
                current_prices=current_prices,
            )
        except Exception:
            logger.exception("Excepción estructural al llenar una orden manual de Paper Trading.")
            raise

        logger.info("Orden manual de Paper Trading llenada: %s.", order_id)
        return result

    def cancel_manual_pending_order(self, order_id: str, cancellation_reason: str) -> CancelOrderResult:
        """Cancela una orden PENDING, liberando su reserva sin liquidar nada.

        No consulta ningún precio (no lo necesita, ver
        ARQUITECTURA_PAPER_TRADING.md §21).
        """
        self._require_enabled("cancel_manual_pending_order")

        try:
            timestamp = self._clock.now()
            result = self._service.cancel_pending_order(
                order_id=order_id,
                cancellation_reason=cancellation_reason,
                timestamp=timestamp,
                currency=self._config.currency,
            )
        except Exception:
            logger.exception("Excepción estructural al cancelar una orden manual de Paper Trading.")
            raise

        logger.info("Orden manual de Paper Trading cancelada: %s.", order_id)
        return result

    # --- Reconciliación administrativa (Etapa 6.8) -------------------------
    #
    # Deliberadamente NO gatea con _require_enabled(): a diferencia de las
    # órdenes manuales de arriba, inspeccionar/reparar no es una acción de
    # trading nueva -- es mantenimiento de datos que debe seguir disponible
    # incluso si `paper_trading.enabled=false` (ej. se deshabilitó
    # precisamente porque se detectó una inconsistencia que hay que poder
    # diagnosticar/reparar antes de reactivar). No expuesto desde el
    # Dashboard (ver §22.11): solo lo usa la CLI administrativa.

    def inspect_reconciliation(self) -> ReconciliationReport:
        """Diagnóstico de solo lectura: nunca escribe nada (§22.6)."""
        timestamp = self._clock.now()
        return self._reconciliation_service.inspect(timestamp)

    def repair_reconciliation(
        self,
        issue_codes: Optional[list[IssueCode]] = None,
        dry_run: bool = True,
    ) -> ReconciliationRepairResult:
        """Repara los issues reparables (§22.7); `dry_run=True` por defecto
        (nunca escribe salvo que se pida explícitamente `dry_run=False`).
        No consulta precios, no genera Order/Execution/Trade ids, no llama
        a ningún método del ciclo de vida de órdenes (accept/fill/cancel)."""
        timestamp = self._clock.now()
        audit_id = self._id_generator.new_reconciliation_audit_id()
        return self._reconciliation_service.repair(
            audit_id=audit_id, timestamp=timestamp, issue_codes=issue_codes, dry_run=dry_run,
        )

    # --- Automatización de inspecciones (Etapa 6.9) -------------------------
    #
    # Mismo criterio que inspect_reconciliation()/repair_reconciliation():
    # deliberadamente NO gatean con _require_enabled() (ver §23.13 -- la
    # inspección/entrega es mantenimiento, no una acción de trading nueva).
    # No exponer estos métodos desde el Dashboard (§23.14).

    def run_reconciliation_inspection(self) -> ScheduledInspectionRun:
        """Ejecuta una inspección manual (delega en InspectionService, que
        a su vez usa ReconciliationService.inspect() -- nunca repair()).
        Usa Clock/IdGenerator inyectados; no consulta precios."""
        timestamp = self._clock.now()
        run_id = self._id_generator.new_inspection_run_id()
        return self._inspection_service.run_inspection(run_id=run_id, started_at=timestamp)

    def deliver_pending_reconciliation_alerts(self) -> AlertDeliveryBatchResult:
        """Entrega las alertas PENDING ya persistidas (delega en
        AlertDeliveryService). No compara reportes ni ejecuta SQL propio."""
        return self._alert_delivery_service.deliver_pending_alerts()

    def fetch_reconciliation_inspection_history(
        self, limit: Optional[int] = None,
    ) -> list[ScheduledInspectionRun]:
        """Historial de corridas de inspección, de solo lectura."""
        return self._repository.fetch_inspection_runs(limit=limit)

    # --- API de compatibilidad (Etapa 6.5) ---------------------------------

    def submit_manual_market_order(
        self,
        exchange: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        source: OrderSource = OrderSource.MANUAL,
        linked_recommendation_id: Optional[str] = None,
    ) -> SubmitOrderResult:
        """Somete una orden MARKET manual de punta a punta (API de
        compatibilidad, ver ARQUITECTURA_PAPER_TRADING.md §21.7):
        equivalente a `accept_manual_market_order()` seguido de
        `fill_manual_pending_order()`, pero delegando directamente a
        `PaperTradingService.submit_market_order()` para conservar
        exactamente el comportamiento ya aprobado en la Etapa 6.5.

        Lanza `PaperTradingDisabledError` de inmediato (antes de
        consultar precios, generar IDs, construir la `Order` o llamar al
        Service) si `paper_trading.enabled` es False. Un rechazo de
        riesgo NO lanza excepción: se devuelve como
        `SubmitOrderResult(success=False, ...)`.
        """
        self._require_enabled("submit_manual_market_order")
        self._validate_new_order_input(exchange, symbol, side, quantity)

        try:
            timestamp = self._clock.now()

            symbol_key = (exchange, symbol)
            current_prices = self._current_prices_for(symbol_key)
            market_price = current_prices[symbol_key]

            order = Order(
                id=self._id_generator.new_order_id(),
                exchange=exchange,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                status=OrderStatus.NEW,
                source=source,
                linked_recommendation_id=linked_recommendation_id,
                created_at=timestamp,
                updated_at=timestamp,
            )

            trade_id = self._id_generator.new_trade_id() if side == OrderSide.SELL else None

            result = self._service.submit_market_order(
                order=order,
                market_price=market_price,
                fee_rate=self._config.fee_rate,
                timestamp=timestamp,
                execution_id=self._id_generator.new_execution_id(),
                max_order_value=self._config.max_order_value,
                max_position_value=self._config.max_position_value,
                rules_version=self._config.rules_version,
                trade_id=trade_id,
                currency=self._config.currency,
                current_prices=current_prices,
            )
        except Exception:
            logger.exception("Excepción estructural al procesar una orden manual de Paper Trading.")
            raise

        if result.success:
            logger.info("Orden manual de Paper Trading aceptada: %s %s %s.", side.value, quantity, symbol)
        else:
            logger.info(
                "Orden manual de Paper Trading rechazada por riesgo: %s (%s).",
                result.risk_result.code, symbol,
            )

        return result
