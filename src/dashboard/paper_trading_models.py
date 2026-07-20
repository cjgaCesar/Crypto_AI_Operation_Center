"""
Modelos de presentación del Dashboard de Paper Trading (Etapa 6.6).

Mismo criterio que src/dashboard/models.py (Etapa 5): modelos Pydantic
puros, sin SQLite, sin Streamlit, sin lógica de negocio. Se mantienen en
un archivo propio (en vez de sumarse a models.py) porque Paper Trading
es un dominio separado con su propia convención de precisión: todo
campo monetario/de cantidad usa `Decimal` (nunca `float`), igual que
`src/paper_trading/models.py` -- estos DTOs solo reordenan/agregan esos
mismos valores para la UI, nunca los recalculan.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide

# Estados posibles de una fila de consistencia de PnL (Paso 10).
PNL_CONSISTENT = "Consistente"
PNL_INCONSISTENT = "Inconsistente"
PNL_NO_POSITION = "Sin posición"
PNL_NO_TRADES = "Sin trades"
PNL_NO_DATA = "Sin datos para validar"

# Estados del indicador GLOBAL de consistencia (distinto de los estados
# por fila de arriba -- ver PaperTradingOverview.pnl_consistency_summary).
PNL_SUMMARY_ALL_CONSISTENT = "Todas consistentes"
PNL_SUMMARY_HAS_INCONSISTENCIES = "Existen inconsistencias"
PNL_SUMMARY_NO_DATA = "Sin datos para validar"


class PaperTradingOverview(BaseModel):
    """Resumen general de la cuenta (Paso 9). Los campos derivados del
    último PortfolioSnapshot quedan en None si todavía no existe ningún
    snapshot -- nunca se recalculan ni se inventan."""

    enabled: bool
    currency: str = Field(min_length=1)
    total_balance: Optional[Decimal] = None
    reserved_balance: Optional[Decimal] = None
    available_balance: Optional[Decimal] = None
    positions_value: Optional[Decimal] = None
    total_equity: Optional[Decimal] = None
    realized_pnl_cumulative: Optional[Decimal] = None
    unrealized_pnl_total: Optional[Decimal] = None
    open_positions_count: int = Field(ge=0, default=0)
    total_trades_count: int = Field(ge=0, default=0)
    last_snapshot_at: Optional[datetime] = None
    has_snapshot: bool = False
    pnl_consistency_summary: str = PNL_NO_DATA


class PositionRow(BaseModel):
    """Una fila de la tabla de posiciones (Paso 12)."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: PositionSide
    quantity: Decimal
    reserved_quantity: Decimal
    average_entry_price: Optional[Decimal] = None
    realized_pnl_to_date: Decimal
    opened_at: Optional[datetime] = None
    updated_at: datetime
    pnl_consistency: str = PNL_NO_DATA


class OrderRow(BaseModel):
    """Una fila de la tabla de órdenes (Paso 13). Sin controles de
    cancelación/reenvío: solo campos de lectura."""

    id: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Optional[Decimal] = None
    status: OrderStatus
    source: OrderSource
    linked_recommendation_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None


class ExecutionRow(BaseModel):
    """Una fila de la tabla de ejecuciones (Paso 14). `notional` es
    únicamente de presentación (quantity * price, con Decimal); nunca se
    persiste."""

    id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    executed_at: datetime
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    quantity: Decimal
    price: Decimal
    fee: Decimal
    notional: Decimal


class TradeRow(BaseModel):
    """Una fila de la tabla de trades cerrados (Paso 15). gross_pnl/fees/
    net_pnl se muestran directamente desde el Trade persistido, nunca
    recalculados."""

    id: str = Field(min_length=1)
    opened_at: datetime
    closed_at: datetime
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: TradeSide
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    exit_execution_id: str = Field(min_length=1)


class EquityPoint(BaseModel):
    """Un punto de la serie 'evolución del patrimonio' (Paso 16, gráfico 1)."""

    timestamp: datetime
    total_equity: Decimal
    realized_pnl_cumulative: Decimal
    unrealized_pnl_total: Decimal


class PnLPoint(BaseModel):
    """Un punto de la serie de PnL por símbolo (Paso 16, gráficos 2-3)."""

    timestamp: datetime
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    unrealized_pnl: Decimal
    realized_pnl_cumulative: Decimal


class SymbolPnLDistribution(BaseModel):
    """Un símbolo y la suma de Trade.net_pnl de todos sus trades cerrados
    (Paso 16, gráfico 4). Solo existe si hay al menos un trade."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    net_pnl_sum: Decimal


class PnLConsistencyRow(BaseModel):
    """Una fila de la sección de auditoría de PnL (Paso 10). El Dashboard
    nunca corrige una inconsistencia: solo la informa."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    position_realized_pnl: Optional[Decimal] = None
    calculated_realized_pnl: Optional[Decimal] = None
    status: str = PNL_NO_DATA


class PaperTradingPageView(BaseModel):
    """Todo lo que necesita la página 'Paper Trading' en una sola llamada."""

    enabled: bool
    initialized: bool
    overview: PaperTradingOverview
    positions: list[PositionRow] = Field(default_factory=list)
    orders: list[OrderRow] = Field(default_factory=list)
    executions: list[ExecutionRow] = Field(default_factory=list)
    trades: list[TradeRow] = Field(default_factory=list)
    equity_history: list[EquityPoint] = Field(default_factory=list)
    pnl_history: list[PnLPoint] = Field(default_factory=list)
    symbol_pnl_distribution: list[SymbolPnLDistribution] = Field(default_factory=list)
    consistency_rows: list[PnLConsistencyRow] = Field(default_factory=list)
    message: Optional[str] = None
