"""
Modelos de dominio de Paper Trading (Etapa 6.1).

Capa de dominio pura: sin SQLite, sin Streamlit, sin lógica de negocio
(eso vive en un futuro motor, ver docs/ARQUITECTURA_PAPER_TRADING.md
§19 -- no implementado en esta iteración). Cada modelo solo valida sus
propios invariantes estructurales, siguiendo el mismo patrón ya usado
en src/models/, src/signals/ y src/ai/ (BaseModel + Field + Optional +
Enum), sumando @model_validator(mode="after") para los invariantes que
cruzan más de un campo -- algo que Field(...) por sí solo no puede
expresar.

Decisión de precisión numérica (Etapa 6.1): Decimal en todo el dominio,
nunca float. La auditoría de arquitectura (Etapa 6.0.1,
ARQUITECTURA_PAPER_TRADING.md §20, punto 1) había recomendado float con
recomputo desde la fuente (consistente con el resto del proyecto); al
aprobar la implementación, el usuario decidió Decimal en su lugar para
este dominio. Es una decisión de implementación explícita de esta
etapa, no una corrección a la arquitectura aprobada.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from src.paper_trading.enums import (
    OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide,
)
from src.paper_trading.validators import ensure_le, ensure_none_iff

ZERO = Decimal("0")

class Order(BaseModel):
    """La intención de operar (simulada), desde que se crea hasta que se resuelve.

    Ver ARQUITECTURA_PAPER_TRADING.md §2.1.
    """

    id: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=ZERO)
    limit_price: Optional[Decimal] = Field(default=None, gt=ZERO)
    status: OrderStatus
    filled_quantity: Decimal = Field(default=ZERO, ge=ZERO)
    average_fill_price: Optional[Decimal] = Field(default=None, gt=ZERO)
    source: OrderSource
    linked_recommendation_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    # Campos de reserva (Etapa 6.7, ver ARQUITECTURA_PAPER_TRADING.md
    # §21.2): opcionales, poblados por ReservationEngine cuando una orden
    # se acepta (NEW -> PENDING) y conservados como registro histórico
    # (nunca se vuelven a None tras liberarse). Deliberadamente NO se
    # exige aquí que estén poblados según `status` (ej. "toda PENDING
    # debe tenerlos"): esa invariante relacional se intentó a nivel de
    # modelo y rompía ~135 pruebas ya aprobadas de motores/Service/
    # repositorio que construyen órdenes PENDING/FILLED/CANCELLED sin
    # ejercitar reservas -- se aplica en su lugar donde realmente importa
    # (ReservationEngine, ver reservation_engine.py), siguiendo el propio
    # criterio del enunciado de la Etapa 6.7 ("si no pueden vivir en
    # modelos aislados, aplicarlas en Service/repositorio").
    reserved_price: Optional[Decimal] = Field(default=None, gt=ZERO)
    reserved_notional: Optional[Decimal] = Field(default=None, ge=ZERO)
    reserved_fee: Optional[Decimal] = Field(default=None, ge=ZERO)
    reserved_quantity: Optional[Decimal] = Field(default=None, gt=ZERO)

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Order":
        ensure_le(self.filled_quantity, self.quantity, "filled_quantity", "quantity")
        ensure_none_iff(
            self.average_fill_price, condition=self.filled_quantity == ZERO,
            value_name="average_fill_price", condition_description="filled_quantity == 0",
        )
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("una orden MARKET no admite limit_price")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("una orden LIMIT requiere limit_price")

        # Los campos de reserva del lado equivocado nunca tienen sentido
        # (ver §21.2): una BUY reserva notional/fee, una SELL reserva
        # cantidad, nunca ambos a la vez para la misma orden.
        if self.side == OrderSide.BUY and self.reserved_quantity is not None:
            raise ValueError("reserved_quantity no aplica a una orden BUY (ver §21.2).")
        if self.side == OrderSide.SELL and (self.reserved_notional is not None or self.reserved_fee is not None):
            raise ValueError("reserved_notional/reserved_fee no aplican a una orden SELL (ver §21.2).")
        return self


class Execution(BaseModel):
    """Un evento de ejecución (fill) individual contra una Order.

    Ver ARQUITECTURA_PAPER_TRADING.md §2.2.
    """

    id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    quantity: Decimal = Field(gt=ZERO)
    price: Decimal = Field(gt=ZERO)
    fee: Decimal = Field(default=ZERO, ge=ZERO)
    executed_at: datetime


class Trade(BaseModel):
    """El cierre, total o parcial, de una posición (evento que realiza PnL).

    Distinto de Execution (un llenado a nivel de orden): un Trade se
    genera cuando una ejecución en sentido contrario reduce o cierra una
    posición existente. Ver ARQUITECTURA_PAPER_TRADING.md §2.3.
    """

    id: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: TradeSide
    quantity: Decimal = Field(gt=ZERO)
    entry_price: Decimal = Field(gt=ZERO)
    exit_price: Decimal = Field(gt=ZERO)
    gross_pnl: Decimal
    fees: Decimal = Field(default=ZERO, ge=ZERO)
    net_pnl: Decimal
    opened_at: datetime
    closed_at: datetime
    exit_execution_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Trade":
        if self.net_pnl != self.gross_pnl - self.fees:
            raise ValueError("net_pnl debe ser exactamente gross_pnl - fees")
        if self.closed_at < self.opened_at:
            raise ValueError("closed_at no puede ser anterior a opened_at")
        return self


class Position(BaseModel):
    """Estado agregado y actual (no histórico) de la exposición en un símbolo.

    Ver ARQUITECTURA_PAPER_TRADING.md §2.4.
    """

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: PositionSide
    quantity: Decimal = Field(ge=ZERO)
    reserved_quantity: Decimal = Field(default=ZERO, ge=ZERO)
    average_entry_price: Optional[Decimal] = Field(default=None, gt=ZERO)
    realized_pnl_to_date: Decimal = Field(default=ZERO)
    opened_at: Optional[datetime] = None
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Position":
        ensure_le(self.reserved_quantity, self.quantity, "reserved_quantity", "quantity")
        is_flat = self.side == PositionSide.FLAT
        if is_flat and self.quantity != ZERO:
            raise ValueError("una posición FLAT debe tener quantity == 0")
        if not is_flat and self.quantity == ZERO:
            raise ValueError("una posición no-FLAT debe tener quantity > 0")
        ensure_none_iff(
            self.average_entry_price, condition=is_flat,
            value_name="average_entry_price", condition_description="side == FLAT",
        )
        return self

    @property
    def available_quantity(self) -> Decimal:
        """Cantidad realmente disponible para vender (§2.4): quantity - reserved_quantity."""
        return self.quantity - self.reserved_quantity


class CashBalance(BaseModel):
    """Capital disponible de la cuenta de Paper Trading (una sola cuenta simulada).

    Ver ARQUITECTURA_PAPER_TRADING.md §2.5.
    """

    currency: str = Field(default="USDT", min_length=1)
    total_balance: Decimal = Field(ge=ZERO)
    reserved_balance: Decimal = Field(default=ZERO, ge=ZERO)
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_invariants(self) -> "CashBalance":
        ensure_le(self.reserved_balance, self.total_balance, "reserved_balance", "total_balance")
        return self

    @property
    def available_balance(self) -> Decimal:
        """Calculado, nunca un campo guardado por separado (§2.5): total_balance - reserved_balance."""
        return self.total_balance - self.reserved_balance


class PortfolioSnapshot(BaseModel):
    """Fila periódica con el estado agregado de toda la cuenta.

    Ver ARQUITECTURA_PAPER_TRADING.md §2.8.
    """

    id: Optional[int] = None
    timestamp: datetime
    cash_balance: Decimal = Field(ge=ZERO)
    positions_value: Decimal = Field(ge=ZERO)
    total_equity: Decimal
    unrealized_pnl_total: Decimal
    realized_pnl_cumulative: Decimal

    @model_validator(mode="after")
    def _validate_invariants(self) -> "PortfolioSnapshot":
        if self.total_equity != self.cash_balance + self.positions_value:
            raise ValueError("total_equity debe ser exactamente cash_balance + positions_value")
        return self


class PnLSnapshot(BaseModel):
    """Igual cadencia que PortfolioSnapshot, pero por símbolo.

    Ver ARQUITECTURA_PAPER_TRADING.md §2.9.
    """

    id: Optional[int] = None
    timestamp: datetime
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    position_quantity: Decimal = Field(ge=ZERO)
    unrealized_pnl: Decimal
    realized_pnl_cumulative: Decimal


class RiskValidationResult(BaseModel):
    """Veredicto de una validación de riesgo sobre una orden propuesta.

    Corresponde a RiskCheckResult en ARQUITECTURA_PAPER_TRADING.md §8.5
    (mismos campos, renombrado por el usuario al aprobar esta
    iteración). Ningún RiskEngine existe todavía en esta etapa: este
    modelo solo declara la forma del resultado que un futuro motor (6.2)
    producirá.
    """

    approved: bool
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    metrics_used: dict[str, Decimal] = Field(default_factory=dict)
    limits_used: dict[str, Decimal] = Field(default_factory=dict)
    timestamp: datetime
    rules_version: str = Field(min_length=1)
