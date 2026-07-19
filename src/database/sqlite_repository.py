"""
Implementación de MarketDataRepository usando SQLite.

SQLite es la base de datos de desarrollo de este proyecto: guarda todo en un
solo archivo, sin necesidad de instalar ni levantar ningún servidor aparte.
Cuando el proyecto lo requiera (mayor volumen de datos, varios procesos
escribiendo a la vez, despliegue en un servidor, etc.), se puede migrar a
PostgresMarketDataRepository (ver src/database/postgres_repository.py) sin
cambiar nada fuera de esta clase, porque ambas implementan la misma interfaz
MarketDataRepository.
"""

from pathlib import Path
import sqlite3
from typing import Optional

from src.database.base import MarketDataRepository
from src.models.market_data import MarketTicker


class SQLiteMarketDataRepository(MarketDataRepository):
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
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL DEFAULT 'Binance',
                    symbol TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume_24h REAL NOT NULL,
                    price_change_percent_24h REAL NOT NULL,
                    queried_at TEXT NOT NULL
                )
                """
            )
            self._migrate_missing_exchange_column(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_missing_exchange_column(self, conn: sqlite3.Connection) -> None:
        """Migra bases de datos creadas antes de que existiera la columna
        'exchange' (primera versión de la Etapa 1.5), sin perder ningún
        registro existente. Los registros previos quedan marcados como
        'Binance', ya que ese fue el único exchange consultado hasta ahora.
        """
        columns = [row[1] for row in conn.execute("PRAGMA table_info(market_data)")]
        if "exchange" not in columns:
            conn.execute(
                "ALTER TABLE market_data ADD COLUMN exchange TEXT NOT NULL DEFAULT 'Binance'"
            )

    def save(self, tickers: list[MarketTicker]) -> None:
        if not tickers:
            return
        conn = self._get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO market_data
                    (exchange, symbol, price, volume_24h, price_change_percent_24h, queried_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        t.exchange,
                        t.symbol,
                        t.price,
                        t.volume_24h,
                        t.price_change_percent_24h,
                        t.queried_at.isoformat(),
                    )
                    for t in tickers
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_all(self) -> list[MarketTicker]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT exchange, symbol, price, volume_24h, price_change_percent_24h, queried_at "
                "FROM market_data ORDER BY id"
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        return [
            MarketTicker(
                exchange=row[0],
                symbol=row[1],
                price=row[2],
                volume_24h=row[3],
                price_change_percent_24h=row[4],
                queried_at=row[5],
            )
            for row in rows
        ]

    def fetch_by_symbol(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[MarketTicker]:
        conn = self._get_connection()
        try:
            if limit is None:
                cursor = conn.execute(
                    "SELECT exchange, symbol, price, volume_24h, price_change_percent_24h, queried_at "
                    "FROM market_data WHERE exchange = ? AND symbol = ? ORDER BY id ASC",
                    (exchange, symbol),
                )
                rows = cursor.fetchall()
            else:
                # Se piden las últimas 'limit' filas (ORDER BY id DESC) y
                # luego se invierten, para devolver siempre de más antigua
                # a más reciente.
                cursor = conn.execute(
                    "SELECT exchange, symbol, price, volume_24h, price_change_percent_24h, queried_at "
                    "FROM market_data WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT ?",
                    (exchange, symbol, limit),
                )
                rows = list(reversed(cursor.fetchall()))
        finally:
            conn.close()

        return [
            MarketTicker(
                exchange=row[0],
                symbol=row[1],
                price=row[2],
                volume_24h=row[3],
                price_change_percent_24h=row[4],
                queried_at=row[5],
            )
            for row in rows
        ]
