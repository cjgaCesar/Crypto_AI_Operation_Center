"""
PaperTradingApplication -- casos de uso de aplicación para Paper Trading (Etapa 6.5).

No es lógica de negocio (eso vive en los motores, Etapa 6.2, orquestada
por PaperTradingService, Etapa 6.4): esta capa solo traduce una
solicitud manual (exchange, symbol, side, quantity) en los argumentos
explícitos que `PaperTradingService.submit_market_order()` necesita --
timestamp (`Clock`), IDs (`IdGenerator`), precio actual
(`MarketPriceProvider`) -- y devuelve el resultado exactamente como lo
produjo el servicio, sin modificarlo.

No calcula riesgo, fees, PnL ni CashBalance; no actualiza `Position`;
no persiste nada por su cuenta; no abre conexiones sqlite3 (todo el
acceso a datos pasa por `PaperTradingRepository`/`PaperTradingService`,
ya inyectados).
"""

import logging
from decimal import Decimal
from typing import Optional

from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
from src.paper_trading.models import Order
from src.paper_trading.price_provider import MarketPriceProvider
from src.paper_trading.runtime import Clock, IdGenerator
from src.paper_trading.service import PaperTradingService
from src.paper_trading.service_results import SubmitOrderResult
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
    """Expone el caso de uso manual de Paper Trading (Etapa 6.5).

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
    ):
        self._service = service
        self._repository = repository
        self._price_provider = price_provider
        self._clock = clock
        self._id_generator = id_generator
        self._config = config

    def submit_manual_market_order(
        self,
        exchange: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        source: OrderSource = OrderSource.MANUAL,
        linked_recommendation_id: Optional[str] = None,
    ) -> SubmitOrderResult:
        """Somete una orden MARKET manual de punta a punta.

        Lanza `PaperTradingDisabledError` de inmediato (antes de
        consultar precios, generar IDs, construir la `Order` o llamar al
        Service) si `paper_trading.enabled` es False. Un rechazo de
        riesgo NO lanza excepción: se devuelve como
        `SubmitOrderResult(success=False, ...)`, igual que hace
        `PaperTradingService.submit_market_order()`.
        """
        if not self._config.enabled:
            logger.info("Orden manual de Paper Trading rechazada: Paper Trading está deshabilitado.")
            raise PaperTradingDisabledError(
                "Paper Trading está deshabilitado (paper_trading.enabled=false)."
            )

        if not exchange:
            raise ValueError("exchange no puede estar vacío.")
        if not symbol:
            raise ValueError("symbol no puede estar vacío.")
        if not isinstance(side, OrderSide):
            raise ValueError(f"side debe ser OrderSide.BUY o OrderSide.SELL; se recibió {side!r}.")
        if quantity <= Decimal("0"):
            raise ValueError("quantity debe ser mayor que 0.")

        try:
            timestamp = self._clock.now()

            # Precios: siempre el símbolo operado + todas las posiciones
            # abiertas no-FLAT (nunca se inventa un precio faltante).
            open_positions = self._repository.fetch_positions(include_flat=False)
            symbol_key = (exchange, symbol)
            price_keys = {(position.exchange, position.symbol) for position in open_positions}
            price_keys.add(symbol_key)
            current_prices = self._price_provider.get_current_prices(list(price_keys))
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

            # Solo una SELL puede generar un Trade (ver PositionEngine);
            # una BUY nunca lo necesita, así que no se genera un id de más.
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
