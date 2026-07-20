"""
PaperTradingService -- orquestación transaccional de Paper Trading (Etapa 6.4,
ampliado en 6.7 con el ciclo explícito aceptar/reservar -> llenar/liberar
-> cancelar/liberar).

Única capa autorizada para mover una orden de Paper Trading entre
estados: valida riesgo (RiskEngine), reserva/libera recursos
(ReservationEngine), simula el llenado (FillEngine), aplica el
resultado sobre la posición (PositionEngine), calcula snapshots
(PnLEngine) y persiste cada paso en una única transacción atómica
(PaperTradingRepository). No implementa ninguna regla de negocio
propia: cada cálculo de dominio ya vive en su motor correspondiente
(Etapa 6.2); este servicio solo los invoca en el orden correcto y
decide qué persistir. Ver docs/ARQUITECTURA_PAPER_TRADING.md §21 para
el diseño completo del ciclo de reservas.

Alcance de esta iteración (ver ARQUITECTURA_PAPER_TRADING.md):
- Solo OrderType.MARKET, solo PositionSide.LONG/FLAT (mismo alcance que
  los motores; ver fill_engine.py/position_engine.py).
- `accept_market_order()` valida riesgo y persiste la orden en PENDING
  con su reserva (CashBalance.reserved_balance para BUY,
  Position.reserved_quantity para SELL) en una transacción atómica.
- `fill_pending_order()` libera esa reserva y liquida: usa siempre
  `order.reserved_price` (nunca un precio nuevo) como precio de
  ejecución -- política "MARKET se llena al precio aceptado" (§21.3).
- `cancel_pending_order()` libera la reserva sin liquidar nada.
- `submit_market_order()` se conserva como fachada de compatibilidad:
  `accept_market_order()` seguido de `fill_pending_order()`. No finge
  una atomicidad que no existe entre ambas transacciones (§21.7): si
  aceptar se persiste y llenar falla, la orden queda legítimamente
  PENDING con su reserva activa (recuperable con las llamadas
  explícitas), no corrupta.
- El snapshot de cartera (`PortfolioSnapshot`) requiere un precio por
  cada posición abierta no-FLAT (ver `PnLEngine.build_portfolio_snapshot`);
  si la cuenta tiene otras posiciones abiertas en otros símbolos, el
  llamador debe proveerlos en `current_prices`; si falta alguno,
  `PnLEngine` falla explícitamente (nunca se inventa un precio).
- Si todavía no existe un `CashBalance` para la moneda solicitada, este
  servicio falla explícitamente con `ValueError` en vez de inventar un
  saldo.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderSide, OrderStatus, PositionSide
from src.paper_trading.exceptions import InvalidOrderStateError
from src.paper_trading.fill_engine import FillEngine
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.pnl_engine import PnLEngine
from src.paper_trading.position_engine import PositionEngine
from src.paper_trading.reservation_engine import ReservationEngine
from src.paper_trading.risk_engine import RiskEngine
from src.paper_trading.service_results import (
    AcceptOrderResult, CancelOrderResult, FillPendingOrderResult, SubmitOrderResult,
)

ZERO = Decimal("0")


class PaperTradingService:
    """Coordina RiskEngine + ReservationEngine + FillEngine + PositionEngine
    + PnLEngine + PaperTradingRepository."""

    def __init__(
        self,
        repository: PaperTradingRepository,
        fill_engine=FillEngine,
        position_engine=PositionEngine,
        pnl_engine=PnLEngine,
        risk_engine=RiskEngine,
        reservation_engine=ReservationEngine,
    ):
        self._repository = repository
        self._fill_engine = fill_engine
        self._position_engine = position_engine
        self._pnl_engine = pnl_engine
        self._risk_engine = risk_engine
        self._reservation_engine = reservation_engine

    # --- Lectura de estado compartida por accept/fill/cancel ---------------

    def _read_position(self, exchange: str, symbol: str, timestamp: datetime) -> Position:
        position = self._repository.get_position(exchange, symbol)
        if position is None:
            return Position(
                exchange=exchange, symbol=symbol, side=PositionSide.FLAT, quantity=ZERO, updated_at=timestamp,
            )
        return position

    def _read_cash_balance(self, currency: str) -> CashBalance:
        cash_balance = self._repository.get_cash_balance(currency)
        if cash_balance is None:
            raise ValueError(
                f"No existe CashBalance para la moneda '{currency}'. Debe sembrarse el "
                "capital inicial antes de poder operar (ver ARQUITECTURA_PAPER_TRADING.md §9.2)."
            )
        return cash_balance

    # --- Fase 1: aceptar (validar riesgo + reservar) -----------------------

    def accept_market_order(
        self,
        order: Order,
        market_price: Decimal,
        fee_rate: Decimal,
        timestamp: datetime,
        max_order_value: Decimal,
        max_position_value: Decimal,
        rules_version: str,
        currency: str = "USDT",
    ) -> AcceptOrderResult:
        """Valida riesgo y, si se aprueba, reserva recursos y persiste la
        orden en PENDING (Etapa 6.7, §21.4-§21.5).

        Un rechazo de riesgo NO lanza excepción: `success=False`, sin
        reservar ni persistir nada. Lanza `InvalidOrderStateError` si ya
        existe una orden con ese id (nunca duplica una reserva).
        """
        if self._repository.get_order(order.id) is not None:
            raise InvalidOrderStateError(f"Ya existe una orden con id {order.id}.")

        position = self._read_position(order.exchange, order.symbol, timestamp)
        cash_balance = self._read_cash_balance(currency)

        risk_result = self._risk_engine.validate_order(
            order=order, cash_balance=cash_balance, position=position, market_price=market_price,
            max_order_value=max_order_value, max_position_value=max_position_value,
            fee_rate=fee_rate, timestamp=timestamp, rules_version=rules_version,
        )
        if not risk_result.approved:
            return AcceptOrderResult(
                success=False, risk_result=risk_result, order=order,
                cash_balance=None, position=None, reservation_created=False,
            )

        reservation = self._reservation_engine.reserve_for_order(
            order=order, cash_balance=cash_balance, position=position,
            market_price=market_price, fee_rate=fee_rate, timestamp=timestamp,
        )

        self._repository.save_order_acceptance_transaction(
            order=reservation.order, cash_balance=reservation.cash_balance, position=reservation.position,
        )

        return AcceptOrderResult(
            success=True, risk_result=risk_result, order=reservation.order,
            cash_balance=reservation.cash_balance, position=reservation.position, reservation_created=True,
        )

    # --- Fase 2: llenar (liberar reserva + liquidar) -----------------------

    def fill_pending_order(
        self,
        order_id: str,
        execution_id: str,
        fee_rate: Decimal,
        timestamp: datetime,
        trade_id: Optional[str] = None,
        currency: str = "USDT",
        current_prices: Optional[dict[tuple[str, str], Decimal]] = None,
    ) -> FillPendingOrderResult:
        """Libera la reserva de una orden PENDING y la liquida.

        Usa siempre `order.reserved_price` como precio de ejecución
        (política "MARKET se llena al precio aceptado", §21.3) -- no
        recibe `market_price` como parámetro. Lanza
        `InvalidOrderStateError` si la orden no existe o no está PENDING
        (nunca llena dos veces, nunca llena una orden cancelada).
        """
        order = self._repository.get_order(order_id)
        if order is None:
            raise InvalidOrderStateError(f"No existe una orden con id {order_id}.")
        if order.status != OrderStatus.PENDING:
            raise InvalidOrderStateError(
                f"Solo se puede llenar una orden PENDING; estado actual: {order.status.value}."
            )

        position = self._read_position(order.exchange, order.symbol, timestamp)
        cash_balance = self._read_cash_balance(currency)

        release = self._reservation_engine.release_for_order(
            order=order, cash_balance=cash_balance, position=position, timestamp=timestamp,
        )

        fill_result = self._fill_engine.execute_market_order(
            order=order, market_price=order.reserved_price, fee_rate=fee_rate,
            executed_at=timestamp, execution_id=execution_id,
        )

        position_result = self._position_engine.apply_execution(
            position=release.position, order=fill_result.order, execution=fill_result.execution,
            updated_at=timestamp, trade_id=trade_id,
        )

        notional = fill_result.execution.quantity * fill_result.execution.price
        if order.side == OrderSide.BUY:
            new_total_balance = release.cash_balance.total_balance - notional - fill_result.execution.fee
        else:
            new_total_balance = release.cash_balance.total_balance + notional - fill_result.execution.fee

        new_cash_balance = CashBalance(
            currency=release.cash_balance.currency,
            total_balance=new_total_balance,
            reserved_balance=release.cash_balance.reserved_balance,
            updated_at=timestamp,
        )

        symbol_key = (order.exchange, order.symbol)
        prices = {symbol_key: order.reserved_price}
        if current_prices:
            prices.update(current_prices)

        other_positions = [
            existing for existing in self._repository.fetch_positions()
            if (existing.exchange, existing.symbol) != symbol_key
        ]
        all_positions = other_positions + [position_result.position]

        portfolio_snapshot = self._pnl_engine.build_portfolio_snapshot(
            cash_balance=new_cash_balance, positions=all_positions, current_prices=prices, timestamp=timestamp,
        )
        pnl_snapshot = self._pnl_engine.build_pnl_snapshot(
            position=position_result.position, current_price=order.reserved_price, timestamp=timestamp,
        )

        self._repository.save_fill_transaction(
            order=fill_result.order,
            execution=fill_result.execution,
            position=position_result.position,
            cash_balance=new_cash_balance,
            trade=position_result.trade,
            portfolio_snapshot=portfolio_snapshot,
            pnl_snapshot=pnl_snapshot,
        )

        return FillPendingOrderResult(
            order=fill_result.order,
            execution=fill_result.execution,
            position=position_result.position,
            trade=position_result.trade,
            cash_balance=new_cash_balance,
            portfolio_snapshot=portfolio_snapshot,
            pnl_snapshot=pnl_snapshot,
            reservation_released=True,
        )

    # --- Cancelar (liberar reserva sin liquidar) ---------------------------

    def cancel_pending_order(
        self,
        order_id: str,
        cancellation_reason: str,
        timestamp: datetime,
        currency: str = "USDT",
    ) -> CancelOrderResult:
        """Libera la reserva de una orden PENDING y la mueve a CANCELLED,
        sin generar Execution ni Trade ni tocar total_balance/quantity.

        Lanza `InvalidOrderStateError` si la orden no existe o no está
        PENDING (nunca cancela dos veces, nunca cancela una orden ya
        llenada).
        """
        if not cancellation_reason:
            raise ValueError("cancellation_reason es obligatorio.")

        order = self._repository.get_order(order_id)
        if order is None:
            raise InvalidOrderStateError(f"No existe una orden con id {order_id}.")
        if order.status != OrderStatus.PENDING:
            raise InvalidOrderStateError(
                f"Solo se puede cancelar una orden PENDING; estado actual: {order.status.value}."
            )

        position = self._read_position(order.exchange, order.symbol, timestamp)
        cash_balance = self._read_cash_balance(currency)

        release = self._reservation_engine.release_for_order(
            order=order, cash_balance=cash_balance, position=position, timestamp=timestamp,
        )

        cancelled_order = Order(**{
            **order.model_dump(),
            "status": OrderStatus.CANCELLED,
            "cancellation_reason": cancellation_reason,
            "updated_at": timestamp,
        })

        self._repository.save_order_cancellation_transaction(
            order=cancelled_order, cash_balance=release.cash_balance, position=release.position,
        )

        return CancelOrderResult(
            order=cancelled_order, cash_balance=release.cash_balance, position=release.position,
            reservation_released=True,
        )

    # --- Fachada de compatibilidad (Etapa 6.4) -----------------------------

    def submit_market_order(
        self,
        order: Order,
        market_price: Decimal,
        fee_rate: Decimal,
        timestamp: datetime,
        execution_id: str,
        max_order_value: Decimal,
        max_position_value: Decimal,
        rules_version: str,
        trade_id: Optional[str] = None,
        currency: str = "USDT",
        current_prices: Optional[dict[tuple[str, str], Decimal]] = None,
    ) -> SubmitOrderResult:
        """Valida y llena una orden MARKET de punta a punta (API de
        compatibilidad, ver §21.7): `accept_market_order()` seguido de
        `fill_pending_order()` con el mismo `timestamp`.

        No finge una atomicidad que no existe entre las dos
        transacciones: si aceptar se persiste y llenar lanza una
        excepción, la orden queda PENDING con su reserva activa en la
        base -- un estado válido y recuperable (puede llenarse o
        cancelarse después con las llamadas explícitas), no una
        corrupción. No muta ningún argumento recibido.
        """
        accept_result = self.accept_market_order(
            order=order, market_price=market_price, fee_rate=fee_rate, timestamp=timestamp,
            max_order_value=max_order_value, max_position_value=max_position_value,
            rules_version=rules_version, currency=currency,
        )
        if not accept_result.success:
            return SubmitOrderResult(
                success=False, risk_result=accept_result.risk_result, order=order, execution=None,
                position=None, trade=None, cash_balance=None, portfolio_snapshot=None, pnl_snapshot=None,
            )

        fill_result = self.fill_pending_order(
            order_id=accept_result.order.id, execution_id=execution_id, fee_rate=fee_rate,
            timestamp=timestamp, trade_id=trade_id, currency=currency, current_prices=current_prices,
        )

        return SubmitOrderResult(
            success=True,
            risk_result=accept_result.risk_result,
            order=fill_result.order,
            execution=fill_result.execution,
            position=fill_result.position,
            trade=fill_result.trade,
            cash_balance=fill_result.cash_balance,
            portfolio_snapshot=fill_result.portfolio_snapshot,
            pnl_snapshot=fill_result.pnl_snapshot,
        )
