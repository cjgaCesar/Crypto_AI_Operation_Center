"""
Tipos de resultado devueltos por ReservationEngine (Etapa 6.7).

Mismo criterio que src/paper_trading/results.py (FillResult/
PositionUpdateResult): NamedTuple, no BaseModel -- no son entidades de
dominio que se persistan ni se validen (eso ya lo hicieron Order/
CashBalance/Position al construirse), son solo el resultado, inmutable,
de una llamada a un motor puro.
"""

from typing import NamedTuple

from src.paper_trading.models import CashBalance, Order, Position


class ReservationResult(NamedTuple):
    """Resultado de ReservationEngine.reserve_for_order().

    `order` queda en PENDING con sus campos de reserva poblados.
    `cash_balance`/`position` reflejan el aumento de la reserva (BUY:
    cash_balance.reserved_balance; SELL: position.reserved_quantity);
    el que no cambia se devuelve tal cual, sin mutar.
    """

    order: Order
    cash_balance: CashBalance
    position: Position


class ReservationReleaseResult(NamedTuple):
    """Resultado de ReservationEngine.release_for_order().

    No incluye `order`: liberar una reserva no cambia el status de la
    orden por sí solo (eso lo decide quien llama -- FILLED al llenar,
    CANCELLED al cancelar). Solo cash_balance/position reflejan la
    disminución de la reserva liberada.
    """

    cash_balance: CashBalance
    position: Position
