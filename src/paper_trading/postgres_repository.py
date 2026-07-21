"""
Implementación futura de PaperTradingRepository usando PostgreSQL.

Este archivo NO se usa todavía en ningún lugar del proyecto -- igual que
src/database/postgres_repository.py, src/signals/postgres_repository.py
y src/ai/postgres_repository.py, se deja preparado para cuando se
decida migrar de SQLite a PostgreSQL. Ninguna dependencia de PostgreSQL
se agrega en esta etapa (ver requirements.txt, sin cambios).

La implementación real deberá usar las mismas 7 tablas que
SQLitePaperTradingRepository (paper_trading_orders, _executions,
_trades, _positions, _cash_balances, _portfolio_snapshots,
_pnl_snapshots -- ver docs/ARQUITECTURA_PAPER_TRADING.md), y podrá
guardar los campos Decimal en una columna NUMERIC nativa de PostgreSQL
en vez de TEXT (a diferencia de SQLite, que no tiene un tipo decimal
exacto).
"""

from decimal import Decimal
from typing import Optional

from src.paper_trading.alert_models import AlertStatus, InspectionAlert
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderStatus
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.models import (
    CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade,
)
from src.paper_trading.reconciliation_models import ReconciliationAuditRecord

_NOT_IMPLEMENTED_MSG = (
    "PostgresPaperTradingRepository todavía no está implementado. "
    "Es solo la estructura preparada para una etapa futura de migración "
    "desde SQLite. Ver docs/ARQUITECTURA_PAPER_TRADING.md."
)


class PostgresPaperTradingRepository(PaperTradingRepository):
    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def init(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_order(self, order: Order) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_order(self, order_id: str) -> Optional[Order]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_orders(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        limit: Optional[int] = None,
    ) -> list[Order]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_execution(self, execution: Execution) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_executions_by_order(self, order_id: str) -> list[Execution]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_executions(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Execution]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_trade(self, trade: Trade) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_trades(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Trade]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_position(self, position: Position) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_position(self, exchange: str, symbol: str) -> Optional[Position]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_positions(self, include_flat: bool = True) -> list[Position]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_cash_balance(self, cash_balance: CashBalance) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_cash_balance(self, currency: str = "USDT") -> Optional[CashBalance]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_portfolio_history(self, limit: Optional[int] = None) -> list[PortfolioSnapshot]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_pnl_snapshot(self, snapshot: PnLSnapshot) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_pnl_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None,
    ) -> list[PnLSnapshot]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_fill_transaction(
        self,
        order: Order,
        execution: Execution,
        position: Position,
        cash_balance: CashBalance,
        trade: Optional[Trade] = None,
        portfolio_snapshot: Optional[PortfolioSnapshot] = None,
        pnl_snapshot: Optional[PnLSnapshot] = None,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_order_acceptance_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_order_cancellation_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def calculate_realized_pnl(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None,
    ) -> Decimal:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def check_position_pnl_consistency(self, exchange: str, symbol: str) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_cash_balances(self) -> list[CashBalance]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_reconciliation_audit_record(self, audit_record: ReconciliationAuditRecord) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_reconciliation_transaction(
        self,
        cash_balances: list[CashBalance],
        positions: list[Position],
        audit_record: ReconciliationAuditRecord,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_latest_successful_inspection_run(self):
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_latest_inspection_run(self):
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_inspection_runs(self, limit: Optional[int] = None) -> list[ScheduledInspectionRun]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_pending_inspection_alerts(self, limit: Optional[int] = None) -> list[InspectionAlert]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def get_inspection_alert_by_deduplication_key(self, deduplication_key: str):
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save_inspection_run_transaction(
        self, run: ScheduledInspectionRun, alerts: list[InspectionAlert],
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def update_inspection_alert_delivery(
        self, alert_id: str, status: AlertStatus, delivery_attempts: int,
        last_error: Optional[str], delivered_at,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
