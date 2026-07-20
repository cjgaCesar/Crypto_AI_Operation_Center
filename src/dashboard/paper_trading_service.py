"""
Servicio del Dashboard de Paper Trading (Etapa 6.6).

Mismo espíritu que src/dashboard/service.py (Etapa 5): coordina
PaperTradingDashboardRepository (solo lectura) y arma los modelos de
presentación (paper_trading_models.py). No ejecuta SQL, no escribe en
SQLite, no recalcula reglas de negocio (fees/PnL/riesgo/posiciones ya
calculados por los motores de la Etapa 6.2 y persistidos por la Etapa
6.3), no importa PaperTradingApplication ni PaperTradingService de
ejecución.

Toda llamada al repositorio pasa por `_safe_call()`/`_safe_list_call()`,
igual criterio que DashboardService: si el repositorio lanza cualquier
excepción inesperada, se registra en el log y se devuelve un resultado
vacío, para que la página nunca se rompa (ni muestre un stacktrace).
"""

import logging
from decimal import Decimal
from typing import Callable, Optional, TypeVar

from src.dashboard.filters import normalize_exchange, normalize_symbol, validate_limit
from src.dashboard.models import DashboardStatus
from src.dashboard.paper_trading_models import (
    PNL_CONSISTENT,
    PNL_INCONSISTENT,
    PNL_NO_DATA,
    PNL_NO_POSITION,
    PNL_NO_TRADES,
    PNL_SUMMARY_ALL_CONSISTENT,
    PNL_SUMMARY_HAS_INCONSISTENCIES,
    PNL_SUMMARY_NO_DATA,
    EquityPoint,
    ExecutionRow,
    OrderRow,
    PaperTradingOverview,
    PaperTradingPageView,
    PnLConsistencyRow,
    PnLPoint,
    PositionRow,
    SymbolPnLDistribution,
    TradeRow,
)
from src.dashboard.paper_trading_repository import PaperTradingDashboardRepository
from src.paper_trading.enums import OrderStatus, PositionSide
from src.paper_trading.models import CashBalance, Execution, Order, PortfolioSnapshot, Position, Trade

logger = logging.getLogger(__name__)

T = TypeVar("T")

_ZERO = Decimal("0")


class PaperTradingDashboardService:
    def __init__(
        self,
        repository: PaperTradingDashboardRepository,
        enabled: bool,
        currency: str,
        default_history_limit: int = 100,
        max_history_limit: int = 1000,
    ):
        self.repository = repository
        self.enabled = enabled
        self.currency = currency
        self.default_history_limit = default_history_limit
        self.max_history_limit = max_history_limit

    def get_page(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        limit: Optional[int] = None,
        include_flat: bool = False,
    ) -> PaperTradingPageView:
        """Arma toda la vista de la página 'Paper Trading' en una sola llamada.

        `exchange`/`symbol` filtran órdenes/ejecuciones/trades mostrados;
        `status` filtra órdenes; `limit` acota cuántos registros
        históricos se muestran (nunca la consistencia/distribución, que
        necesitan el conjunto completo para ser correctas). `include_flat`
        decide si la tabla de posiciones incluye las ya cerradas (FLAT).
        """
        resolved_exchange = normalize_exchange(exchange) if exchange else None
        resolved_symbol = normalize_symbol(symbol) if symbol else None
        resolved_limit = validate_limit(
            limit, default=self.default_history_limit, maximum=self.max_history_limit,
        )

        dashboard_status = self._safe_call(
            self.repository.get_status,
            fallback=DashboardStatus(database_path="(no disponible)", database_exists=False, tables=[]),
        )
        initialized = any(table.exists for table in dashboard_status.tables)

        if not initialized:
            return PaperTradingPageView(
                enabled=self.enabled,
                initialized=False,
                overview=PaperTradingOverview(enabled=self.enabled, currency=self.currency),
                message="Paper Trading aún no ha sido inicializado.",
            )

        cash_balance = self._safe_call(lambda: self.repository.get_cash_balance(self.currency))

        all_positions = self._safe_list_call(lambda: self.repository.get_positions(include_flat=True))
        displayed_positions = (
            all_positions if include_flat
            else [position for position in all_positions if position.side != PositionSide.FLAT]
        )
        open_positions_count = len(
            [position for position in all_positions if position.side != PositionSide.FLAT]
        )

        # Sin límite a propósito: la consistencia y la distribución por
        # símbolo necesitan el conjunto completo para ser correctas (ver
        # Paso 10/16); la tabla de trades mostrada sí se acota más abajo.
        all_trades = self._safe_list_call(
            lambda: self.repository.get_trades(exchange=resolved_exchange, symbol=resolved_symbol)
        )

        consistency_map = self._build_consistency_map(all_positions, all_trades)
        consistency_rows = [
            PnLConsistencyRow(
                exchange=exchange_key, symbol=symbol_key,
                position_realized_pnl=info["position_realized_pnl"],
                calculated_realized_pnl=info["calculated_realized_pnl"],
                status=info["status"],
            )
            for (exchange_key, symbol_key), info in sorted(consistency_map.items())
        ]

        portfolio_history_desc = self._safe_list_call(
            lambda: self.repository.get_portfolio_history(limit=resolved_limit)
        )
        latest_snapshot = portfolio_history_desc[0] if portfolio_history_desc else None

        overview = self._build_overview(
            cash_balance=cash_balance,
            latest_snapshot=latest_snapshot,
            open_positions_count=open_positions_count,
            total_trades_count=len(all_trades),
            consistency_rows=consistency_rows,
        )

        orders = self._safe_list_call(
            lambda: self.repository.get_orders(
                exchange=resolved_exchange, symbol=resolved_symbol, status=status, limit=resolved_limit,
            )
        )
        executions = self._safe_list_call(
            lambda: self.repository.get_executions(
                exchange=resolved_exchange, symbol=resolved_symbol, limit=resolved_limit,
            )
        )
        # all_trades ya viene ordenado más-reciente-primero (Etapa 6.3);
        # acotar para mostrar es un simple slice, no una consulta nueva.
        trades_for_display = all_trades[:resolved_limit]

        equity_history = [
            EquityPoint(
                timestamp=snapshot.timestamp, total_equity=snapshot.total_equity,
                realized_pnl_cumulative=snapshot.realized_pnl_cumulative,
                unrealized_pnl_total=snapshot.unrealized_pnl_total,
            )
            for snapshot in reversed(portfolio_history_desc)
        ]

        pnl_history: list[PnLPoint] = []
        if resolved_symbol:
            pnl_snapshots_desc = self._safe_list_call(
                lambda: self.repository.get_pnl_history(
                    resolved_exchange or "Binance", resolved_symbol, limit=resolved_limit,
                )
            )
            pnl_history = [
                PnLPoint(
                    timestamp=snap.timestamp, exchange=snap.exchange, symbol=snap.symbol,
                    unrealized_pnl=snap.unrealized_pnl, realized_pnl_cumulative=snap.realized_pnl_cumulative,
                )
                for snap in reversed(pnl_snapshots_desc)
            ]

        return PaperTradingPageView(
            enabled=self.enabled,
            initialized=True,
            overview=overview,
            positions=[
                self._build_position_row(position, consistency_map) for position in displayed_positions
            ],
            orders=[self._build_order_row(order) for order in orders],
            executions=[self._build_execution_row(execution) for execution in executions],
            trades=[self._build_trade_row(trade) for trade in trades_for_display],
            equity_history=equity_history,
            pnl_history=pnl_history,
            symbol_pnl_distribution=self._build_symbol_pnl_distribution(all_trades),
            consistency_rows=consistency_rows,
            message=None,
        )

    def _build_overview(
        self,
        cash_balance: Optional[CashBalance],
        latest_snapshot: Optional[PortfolioSnapshot],
        open_positions_count: int,
        total_trades_count: int,
        consistency_rows: list[PnLConsistencyRow],
    ) -> PaperTradingOverview:
        # "Sin posición"/"Sin trades" no son inconsistencias: son estados
        # donde la consistencia no aplica todavía (nunca se evaluó). Solo
        # una fila explícitamente "Inconsistente" dispara la alerta global.
        if not consistency_rows:
            pnl_consistency_summary = PNL_SUMMARY_NO_DATA
        elif any(row.status == PNL_INCONSISTENT for row in consistency_rows):
            pnl_consistency_summary = PNL_SUMMARY_HAS_INCONSISTENCIES
        else:
            pnl_consistency_summary = PNL_SUMMARY_ALL_CONSISTENT

        return PaperTradingOverview(
            enabled=self.enabled,
            currency=self.currency,
            total_balance=cash_balance.total_balance if cash_balance else None,
            reserved_balance=cash_balance.reserved_balance if cash_balance else None,
            available_balance=cash_balance.available_balance if cash_balance else None,
            positions_value=latest_snapshot.positions_value if latest_snapshot else None,
            total_equity=latest_snapshot.total_equity if latest_snapshot else None,
            realized_pnl_cumulative=latest_snapshot.realized_pnl_cumulative if latest_snapshot else None,
            unrealized_pnl_total=latest_snapshot.unrealized_pnl_total if latest_snapshot else None,
            open_positions_count=open_positions_count,
            total_trades_count=total_trades_count,
            last_snapshot_at=latest_snapshot.timestamp if latest_snapshot else None,
            has_snapshot=latest_snapshot is not None,
            pnl_consistency_summary=pnl_consistency_summary,
        )

    def _build_consistency_map(self, positions: list[Position], trades: list[Trade]) -> dict:
        """Una entrada por cada (exchange, symbol) que tenga Position y/o
        Trade -- ver Paso 10 (Consistente/Inconsistente/Sin posición/Sin
        trades)."""
        symbol_keys = {(p.exchange, p.symbol) for p in positions} | {(t.exchange, t.symbol) for t in trades}

        consistency_map = {}
        for exchange, symbol in symbol_keys:
            position = next((p for p in positions if p.exchange == exchange and p.symbol == symbol), None)
            symbol_trades = [t for t in trades if t.exchange == exchange and t.symbol == symbol]
            calculated = self._safe_call(
                lambda ex=exchange, sy=symbol: self.repository.calculate_realized_pnl(exchange=ex, symbol=sy),
                fallback=_ZERO,
            )

            if position is None:
                consistency_map[(exchange, symbol)] = {
                    "position_realized_pnl": None, "calculated_realized_pnl": calculated,
                    "status": PNL_NO_POSITION,
                }
                continue

            if not symbol_trades:
                consistency_map[(exchange, symbol)] = {
                    "position_realized_pnl": position.realized_pnl_to_date,
                    "calculated_realized_pnl": calculated,
                    "status": PNL_NO_TRADES,
                }
                continue

            consistent = self._safe_call(
                lambda ex=exchange, sy=symbol: self.repository.check_position_pnl_consistency(ex, sy),
                fallback=False,
            )
            consistency_map[(exchange, symbol)] = {
                "position_realized_pnl": position.realized_pnl_to_date,
                "calculated_realized_pnl": calculated,
                "status": PNL_CONSISTENT if consistent else PNL_INCONSISTENT,
            }

        return consistency_map

    @staticmethod
    def _build_position_row(position: Position, consistency_map: dict) -> PositionRow:
        status = consistency_map.get((position.exchange, position.symbol), {}).get("status", PNL_NO_DATA)
        return PositionRow(
            exchange=position.exchange, symbol=position.symbol, side=position.side,
            quantity=position.quantity, reserved_quantity=position.reserved_quantity,
            average_entry_price=position.average_entry_price,
            realized_pnl_to_date=position.realized_pnl_to_date,
            opened_at=position.opened_at, updated_at=position.updated_at,
            pnl_consistency=status,
        )

    @staticmethod
    def _build_order_row(order: Order) -> OrderRow:
        return OrderRow(
            id=order.id, created_at=order.created_at, updated_at=order.updated_at,
            exchange=order.exchange, symbol=order.symbol, side=order.side, order_type=order.order_type,
            quantity=order.quantity, filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price, status=order.status, source=order.source,
            linked_recommendation_id=order.linked_recommendation_id,
            rejection_reason=order.rejection_reason, cancellation_reason=order.cancellation_reason,
        )

    @staticmethod
    def _build_execution_row(execution: Execution) -> ExecutionRow:
        return ExecutionRow(
            id=execution.id, order_id=execution.order_id, executed_at=execution.executed_at,
            exchange=execution.exchange, symbol=execution.symbol, quantity=execution.quantity,
            price=execution.price, fee=execution.fee,
            notional=execution.quantity * execution.price,
        )

    @staticmethod
    def _build_trade_row(trade: Trade) -> TradeRow:
        return TradeRow(
            id=trade.id, opened_at=trade.opened_at, closed_at=trade.closed_at,
            exchange=trade.exchange, symbol=trade.symbol, side=trade.side, quantity=trade.quantity,
            entry_price=trade.entry_price, exit_price=trade.exit_price, gross_pnl=trade.gross_pnl,
            fees=trade.fees, net_pnl=trade.net_pnl, exit_execution_id=trade.exit_execution_id,
        )

    @staticmethod
    def _build_symbol_pnl_distribution(trades: list[Trade]) -> list[SymbolPnLDistribution]:
        if not trades:
            return []
        totals: dict = {}
        for trade in trades:
            key = (trade.exchange, trade.symbol)
            totals[key] = totals.get(key, _ZERO) + trade.net_pnl
        return [
            SymbolPnLDistribution(exchange=exchange, symbol=symbol, net_pnl_sum=total)
            for (exchange, symbol), total in sorted(totals.items())
        ]

    @staticmethod
    def _safe_call(func: Callable[[], T], fallback: Optional[T] = None) -> Optional[T]:
        try:
            return func()
        except Exception:
            logger.warning("PaperTradingDashboardRepository lanzó una excepción inesperada.", exc_info=True)
            return fallback

    def _safe_list_call(self, func: Callable[[], list]) -> list:
        return self._safe_call(func, fallback=[]) or []
