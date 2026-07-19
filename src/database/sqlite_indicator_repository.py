"""
Implementación de IndicatorRepository usando SQLite.

Guarda los indicadores calculados en una tabla independiente,
'market_indicators', separada de 'market_data' (que usa
SQLiteMarketDataRepository). Esta separación permite:

- Mantener 'market_data' con únicamente datos crudos del mercado.
- Recalcular indicadores históricos si cambian los periodos de config.yaml,
  sin tener que volver a consultar Binance.
- Migrar a PostgreSQL de forma independiente para cada tabla en el futuro
  (ver src/database/postgres_indicator_repository.py).
"""

from pathlib import Path
import sqlite3
from typing import Optional

from src.database.base import IndicatorRepository
from src.models.indicator_data import IndicatorSnapshot

_COLUMNS = (
    "exchange", "symbol", "sma", "ema_fast", "ema_medium", "ema_slow", "rsi",
    "macd_line", "macd_signal", "macd_histogram",
    "bollinger_upper", "bollinger_middle", "bollinger_lower",
    "vwap", "calculated_at",
)


class SQLiteIndicatorRepository(IndicatorRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path)

    def init(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_indicators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    sma REAL,
                    ema_fast REAL,
                    ema_medium REAL,
                    ema_slow REAL,
                    rsi REAL,
                    macd_line REAL,
                    macd_signal REAL,
                    macd_histogram REAL,
                    bollinger_upper REAL,
                    bollinger_middle REAL,
                    bollinger_lower REAL,
                    vwap REAL,
                    calculated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, snapshot: IndicatorSnapshot) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                f"""
                INSERT INTO market_indicators ({', '.join(_COLUMNS)})
                VALUES ({', '.join(['?'] * len(_COLUMNS))})
                """,
                (
                    snapshot.exchange,
                    snapshot.symbol,
                    snapshot.sma,
                    snapshot.ema_fast,
                    snapshot.ema_medium,
                    snapshot.ema_slow,
                    snapshot.rsi,
                    snapshot.macd_line,
                    snapshot.macd_signal,
                    snapshot.macd_histogram,
                    snapshot.bollinger_upper,
                    snapshot.bollinger_middle,
                    snapshot.bollinger_lower,
                    snapshot.vwap,
                    snapshot.calculated_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_latest(self, exchange: str, symbol: str) -> Optional[IndicatorSnapshot]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM market_indicators "
                "WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT 1",
                (exchange, symbol),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        return self._row_to_snapshot(row) if row else None

    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[IndicatorSnapshot]:
        conn = self._get_connection()
        try:
            if limit is None:
                cursor = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM market_indicators "
                    "WHERE exchange = ? AND symbol = ? ORDER BY id ASC",
                    (exchange, symbol),
                )
                rows = cursor.fetchall()
            else:
                cursor = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM market_indicators "
                    "WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT ?",
                    (exchange, symbol, limit),
                )
                rows = list(reversed(cursor.fetchall()))
        finally:
            conn.close()

        return [self._row_to_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_snapshot(row) -> IndicatorSnapshot:
        return IndicatorSnapshot(
            exchange=row[0],
            symbol=row[1],
            sma=row[2],
            ema_fast=row[3],
            ema_medium=row[4],
            ema_slow=row[5],
            rsi=row[6],
            macd_line=row[7],
            macd_signal=row[8],
            macd_histogram=row[9],
            bollinger_upper=row[10],
            bollinger_middle=row[11],
            bollinger_lower=row[12],
            vwap=row[13],
            calculated_at=row[14],
        )
