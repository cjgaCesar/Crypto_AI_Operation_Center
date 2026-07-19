"""
Repositorio de solo lectura del Dashboard (Etapa 5).

DashboardRepository (interfaz) y SQLiteDashboardRepository (única
implementación hoy) exponen exactamente lo que las páginas del Dashboard
necesitan leer de las 4 tablas ya generadas por las Etapas 1 a 4, sin
agregar ninguna capacidad de escritura:

- Nunca llama a save() ni init() de ningún repositorio existente.
- Nunca ejecuta INSERT, UPDATE ni DELETE.
- Nunca crea la base de datos ni ejecuta ninguna migración: si el archivo
  SQLite no existe todavía, cada método devuelve None/[] o un
  DashboardStatus con database_exists=False, sin tocar el disco.
- Las consultas propias (las que no tienen un método equivalente en los
  repositorios existentes: listar símbolos, contar filas por tabla) abren
  su propia conexión en modo solo lectura ('file:...?mode=ro'), que
  SQLite rechaza si el archivo no existe, en vez de crearlo.

Para 'get_latest_*'/'*_history', se reutilizan los 4 repositorios ya
existentes (SQLiteMarketDataRepository, SQLiteIndicatorRepository,
SQLiteSignalRepository, SQLiteAIRepository) llamando únicamente a sus
métodos fetch_latest/fetch_by_symbol/fetch_history. No se reimplementa esa
lógica de lectura para no duplicarla, pero si una tabla en particular no
existe todavía (ej. 'market_signals' antes del primer ciclo completo),
esos métodos delegados devuelven None/[] en vez de propagar el error de
SQLite, con el mismo criterio que el resto de este archivo.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import sqlite3
from typing import Optional

from src.ai.recommendation import AIRecommendation
from src.ai.sqlite_repository import SQLiteAIRepository
from src.dashboard.models import DashboardStatus, TableStatus
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.sqlite_repository import SQLiteSignalRepository


class DashboardRepository(ABC):
    """Contrato de solo lectura para el Dashboard. Ningún método de esta
    interfaz permite escribir: no existe (ni debe agregarse) save(),
    insert(), update() ni delete() público."""

    @abstractmethod
    def get_available_symbols(self) -> list[str]:
        """Símbolos con al menos un registro en market_data, ordenados
        alfabéticamente. Lista vacía si la base no existe o está vacía."""

    @abstractmethod
    def get_table_status(self) -> DashboardStatus:
        """Estado técnico del archivo SQLite y de las 4 tablas."""

    @abstractmethod
    def get_latest_market(self, exchange: str, symbol: str) -> Optional[MarketTicker]:
        pass

    @abstractmethod
    def get_latest_indicators(self, exchange: str, symbol: str) -> Optional[IndicatorSnapshot]:
        pass

    @abstractmethod
    def get_latest_signal(self, exchange: str, symbol: str) -> Optional[SignalSnapshot]:
        pass

    @abstractmethod
    def get_latest_ai_recommendation(self, exchange: str, symbol: str) -> Optional[AIRecommendation]:
        pass

    @abstractmethod
    def get_market_history(self, exchange: str, symbol: str, limit: int) -> list[MarketTicker]:
        pass

    @abstractmethod
    def get_indicator_history(self, exchange: str, symbol: str, limit: int) -> list[IndicatorSnapshot]:
        pass

    @abstractmethod
    def get_signal_history(self, exchange: str, symbol: str, limit: int) -> list[SignalSnapshot]:
        pass

    @abstractmethod
    def get_ai_history(self, exchange: str, symbol: str, limit: int) -> list[AIRecommendation]:
        pass


class SQLiteDashboardRepository(DashboardRepository):
    # (nombre de tabla -> columna de timestamp usada para "más reciente").
    _TABLE_TIMESTAMP_COLUMNS = {
        "market_data": "queried_at",
        "market_indicators": "calculated_at",
        "market_signals": "generated_at",
        "ai_recommendations": "created_at",
    }

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._market_repository = SQLiteMarketDataRepository(db_path)
        self._indicator_repository = SQLiteIndicatorRepository(db_path)
        self._signal_repository = SQLiteSignalRepository(db_path)
        self._ai_repository = SQLiteAIRepository(db_path)

    def _database_exists(self) -> bool:
        return Path(self.db_path).exists()

    def _get_readonly_connection(self) -> sqlite3.Connection:
        """Abre el archivo SQLite en modo solo lectura (SQLite rechaza
        crear el archivo si no existe, a diferencia de sqlite3.connect()
        normal). Solo se usa para las 2 consultas que no tienen un método
        equivalente en los repositorios existentes."""
        uri = f"file:{Path(self.db_path).as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def get_available_symbols(self) -> list[str]:
        if not self._database_exists():
            return []
        try:
            conn = self._get_readonly_connection()
            try:
                cursor = conn.execute("SELECT DISTINCT symbol FROM market_data ORDER BY symbol")
                return [row[0] for row in cursor.fetchall()]
            finally:
                conn.close()
        except sqlite3.OperationalError:
            # Base inexistente (carrera con _database_exists) o tabla
            # 'market_data' todavía no creada: sin símbolos disponibles.
            return []

    def get_table_status(self) -> DashboardStatus:
        database_exists = self._database_exists()
        empty_tables = [
            TableStatus(table_name=name, exists=False)
            for name in self._TABLE_TIMESTAMP_COLUMNS
        ]

        if not database_exists:
            return DashboardStatus(
                database_path=self.db_path, database_exists=False, tables=empty_tables,
            )

        try:
            conn = self._get_readonly_connection()
            try:
                tables = [
                    self._table_status(conn, table_name, ts_column)
                    for table_name, ts_column in self._TABLE_TIMESTAMP_COLUMNS.items()
                ]
            finally:
                conn.close()
        except sqlite3.OperationalError:
            tables = empty_tables

        return DashboardStatus(
            database_path=self.db_path, database_exists=database_exists, tables=tables,
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

        return TableStatus(
            table_name=table_name, exists=True, row_count=row_count,
            latest_timestamp=latest_timestamp,
        )

    def get_latest_market(self, exchange: str, symbol: str) -> Optional[MarketTicker]:
        if not self._database_exists():
            return None
        try:
            tickers = self._market_repository.fetch_by_symbol(exchange, symbol, limit=1)
            return tickers[-1] if tickers else None
        except sqlite3.OperationalError:
            return None

    def get_latest_indicators(self, exchange: str, symbol: str) -> Optional[IndicatorSnapshot]:
        if not self._database_exists():
            return None
        try:
            return self._indicator_repository.fetch_latest(exchange, symbol)
        except sqlite3.OperationalError:
            return None

    def get_latest_signal(self, exchange: str, symbol: str) -> Optional[SignalSnapshot]:
        if not self._database_exists():
            return None
        try:
            return self._signal_repository.fetch_latest(exchange, symbol)
        except sqlite3.OperationalError:
            return None

    def get_latest_ai_recommendation(self, exchange: str, symbol: str) -> Optional[AIRecommendation]:
        if not self._database_exists():
            return None
        try:
            return self._ai_repository.fetch_latest(exchange, symbol)
        except sqlite3.OperationalError:
            return None

    def get_market_history(self, exchange: str, symbol: str, limit: int) -> list[MarketTicker]:
        if not self._database_exists():
            return []
        try:
            return self._market_repository.fetch_by_symbol(exchange, symbol, limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_indicator_history(self, exchange: str, symbol: str, limit: int) -> list[IndicatorSnapshot]:
        if not self._database_exists():
            return []
        try:
            return self._indicator_repository.fetch_history(exchange, symbol, limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_signal_history(self, exchange: str, symbol: str, limit: int) -> list[SignalSnapshot]:
        if not self._database_exists():
            return []
        try:
            return self._signal_repository.fetch_history(exchange, symbol, limit=limit)
        except sqlite3.OperationalError:
            return []

    def get_ai_history(self, exchange: str, symbol: str, limit: int) -> list[AIRecommendation]:
        if not self._database_exists():
            return []
        try:
            return self._ai_repository.fetch_history(exchange, symbol, limit=limit)
        except sqlite3.OperationalError:
            return []
