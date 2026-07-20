"""
Repositorio de solo lectura para el Dashboard de Paper Trading (Etapa 6.6).

Mismo criterio exacto que src/dashboard/repository.py (Etapa 5):

- Ningún método de esta interfaz permite escribir: no existe (ni debe
  agregarse) ningún `save_*`, `seed_initial_cash_balance`,
  `submit_market_order`, `submit_manual_market_order` ni `init`.
- Nunca llama a un método de escritura de `PaperTradingRepository`
  (`save_order`, `save_execution`, `save_trade`, `save_position`,
  `save_cash_balance`, `save_fill_transaction`) ni a `.init()`.
- Nunca crea la base de datos ni ejecuta ninguna migración: si el
  archivo SQLite no existe todavía, o si existe pero las tablas
  `paper_trading_*` nunca se crearon, cada método devuelve None/[]/
  Decimal("0")/False, sin tocar el disco.
- Reutiliza los métodos de lectura ya existentes de
  `PaperTradingRepository` (Etapa 6.3) -- no reimplementa esa lógica con
  SQL propio. La única consulta SQL propia de este archivo es
  `get_status()`, exactamente análoga a
  `SQLiteDashboardRepository.get_table_status()`: una introspección de
  `sqlite_master` en modo `mode=ro`, sin la cual no habría forma de
  distinguir "Paper Trading nunca se inicializó" de "inicializado pero
  todavía sin datos".
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Optional

from src.dashboard.models import DashboardStatus, TableStatus
from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderStatus
from src.paper_trading.models import (
    CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade,
)

_TABLE_TIMESTAMP_COLUMNS = {
    "paper_trading_orders": "updated_at",
    "paper_trading_executions": "executed_at",
    "paper_trading_trades": "closed_at",
    "paper_trading_positions": "updated_at",
    "paper_trading_cash_balances": "updated_at",
    "paper_trading_portfolio_snapshots": "timestamp",
    "paper_trading_pnl_snapshots": "timestamp",
}


class PaperTradingDashboardRepository(ABC):
    """Contrato de solo lectura para el Dashboard de Paper Trading. Ningún
    método de esta interfaz permite escribir."""

    @abstractmethod
    def get_status(self) -> DashboardStatus:
        """Estado técnico del archivo SQLite y de las 7 tablas paper_trading_*."""

    @abstractmethod
    def get_cash_balance(self, currency: str = "USDT") -> Optional[CashBalance]:
        pass

    @abstractmethod
    def get_positions(self, include_flat: bool = False) -> list[Position]:
        pass

    @abstractmethod
    def get_orders(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        limit: Optional[int] = None,
    ) -> list[Order]:
        pass

    @abstractmethod
    def get_executions(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None, limit: Optional[int] = None,
    ) -> list[Execution]:
        pass

    @abstractmethod
    def get_trades(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None, limit: Optional[int] = None,
    ) -> list[Trade]:
        pass

    @abstractmethod
    def get_portfolio_history(self, limit: Optional[int] = None) -> list[PortfolioSnapshot]:
        pass

    @abstractmethod
    def get_pnl_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None,
    ) -> list[PnLSnapshot]:
        pass

    @abstractmethod
    def calculate_realized_pnl(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None,
    ) -> Decimal:
        pass

    @abstractmethod
    def check_position_pnl_consistency(self, exchange: str, symbol: str) -> bool:
        pass


class RepositoryPaperTradingDashboardRepository(PaperTradingDashboardRepository):
    def __init__(self, repository: PaperTradingRepository, database_path: str):
        self._repository = repository
        self.database_path = database_path

    def _database_exists(self) -> bool:
        return Path(self.database_path).exists()

    def _get_readonly_connection(self) -> sqlite3.Connection:
        """Solo se usa para get_status() (ver docstring del módulo)."""
        uri = f"file:{Path(self.database_path).as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def get_status(self) -> DashboardStatus:
        database_exists = self._database_exists()
        empty_tables = [
            TableStatus(table_name=name, exists=False) for name in _TABLE_TIMESTAMP_COLUMNS
        ]

        if not database_exists:
            return DashboardStatus(
                database_path=self.database_path, database_exists=False, tables=empty_tables,
            )

        try:
            conn = self._get_readonly_connection()
            try:
                tables = [
                    self._table_status(conn, table_name, ts_column)
                    for table_name, ts_column in _TABLE_TIMESTAMP_COLUMNS.items()
                ]
            finally:
                conn.close()
        except sqlite3.OperationalError:
            tables = empty_tables

        return DashboardStatus(
            database_path=self.database_path, database_exists=database_exists, tables=tables,
        )

    @staticmethod
    def _table_status(conn: sqlite3.Connection, table_name: str, ts_column: str) -> TableStatus:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone() is not None

        if not exists:
            return TableStatus(table_name=table_name, exists=False)

        row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        latest_timestamp = conn.execute(f"SELECT MAX({ts_column}) FROM {table_name}").fetchone()[0]

        return TableStatus(table_name=table_name, exists=True, row_count=row_count, latest_timestamp=latest_timestamp)

    def get_cash_balance(self, currency: str = "USDT") -> Optional[CashBalance]:
        if not self._database_exists():
            return None
        try:
            return self._repository.get_cash_balance(currency)
        except sqlite3.OperationalError:
            return None

    def get_positions(self, include_flat: bool = False) -> list[Position]:
        if not self._database_exists():
            return []
        try:
            return self._repository.fetch_positions(include_flat=include_flat)
        except sqlite3.OperationalError:
            return []

    def get_orders(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        limit: Optional[int] = None,
    ) -> list[Order]:
        if not self._database_exists():
            return []
        try:
            return self._repository.fetch_orders(exchange=exchange, symbol=symbol, status=status, limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_executions(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None, limit: Optional[int] = None,
    ) -> list[Execution]:
        if not self._database_exists():
            return []
        try:
            return self._repository.fetch_executions(exchange=exchange, symbol=symbol, limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_trades(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None, limit: Optional[int] = None,
    ) -> list[Trade]:
        if not self._database_exists():
            return []
        try:
            return self._repository.fetch_trades(exchange=exchange, symbol=symbol, limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_portfolio_history(self, limit: Optional[int] = None) -> list[PortfolioSnapshot]:
        if not self._database_exists():
            return []
        try:
            return self._repository.fetch_portfolio_history(limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_pnl_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None,
    ) -> list[PnLSnapshot]:
        if not self._database_exists():
            return []
        try:
            return self._repository.fetch_pnl_history(exchange, symbol, limit=limit)
        except sqlite3.OperationalError:
            return []

    def calculate_realized_pnl(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None,
    ) -> Decimal:
        if not self._database_exists():
            return Decimal("0")
        try:
            return self._repository.calculate_realized_pnl(exchange=exchange, symbol=symbol)
        except sqlite3.OperationalError:
            return Decimal("0")

    def check_position_pnl_consistency(self, exchange: str, symbol: str) -> bool:
        if not self._database_exists():
            return False
        try:
            return self._repository.check_position_pnl_consistency(exchange, symbol)
        except sqlite3.OperationalError:
            return False
