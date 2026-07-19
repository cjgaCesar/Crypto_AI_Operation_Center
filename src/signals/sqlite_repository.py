"""
Implementación de SignalRepository usando SQLite.

Guarda las señales generadas en una tabla nueva e independiente,
'market_signals', separada tanto de 'market_data' (Etapa 1/1.5) como de
'market_indicators' (Etapa 2). Ninguna de esas dos tablas se modifica en
esta etapa: cada una conserva su propia responsabilidad (datos crudos,
indicadores calculados, señales derivadas).

Además del resultado final, la tabla guarda el 'reason' y la 'strength' de
cada regla (trend_reason/trend_rule_strength, etc.) y el veredicto general
(signal_type), para que una futura IA pueda explicar una señal sin
recalcular nada.

Los campos de categoría de SignalSnapshot son Enums (no str sueltos): esta
clase los serializa explícitamente a texto (.value) al guardarlos en
SQLite (columnas TEXT), y Pydantic los reconstruye automáticamente como
Enum al leer la fila de vuelta (SignalSnapshot valida y convierte el texto
plano al Enum correspondiente).
"""

from pathlib import Path
import sqlite3
from typing import Optional

from src.signals.base import SignalRepository
from src.models.signal_data import SignalSnapshot

_COLUMNS = (
    "exchange", "symbol",
    "trend", "trend_strength", "ema_signal", "macd_signal", "rsi_signal", "bollinger_signal",
    "trend_reason", "ema_reason", "macd_reason", "rsi_reason", "bollinger_reason",
    "trend_rule_strength", "ema_rule_strength", "macd_rule_strength",
    "rsi_rule_strength", "bollinger_rule_strength",
    "score", "confidence", "signal_type", "generated_at",
)

# Columnas agregadas después de la primera versión de la tabla, con su tipo
# SQL y el valor por defecto que reciben los registros ya existentes (para
# no perder ni alterar ningún dato al migrar). Cada tupla es
# (columna, tipo_sql, valor_por_defecto_sql).
_MIGRATION_COLUMNS = [
    ("trend_reason", "TEXT", "''"),
    ("ema_reason", "TEXT", "''"),
    ("macd_reason", "TEXT", "''"),
    ("rsi_reason", "TEXT", "''"),
    ("bollinger_reason", "TEXT", "''"),
    ("signal_type", "TEXT", "'Neutral'"),
    ("trend_rule_strength", "REAL", "0.0"),
    ("ema_rule_strength", "REAL", "0.0"),
    ("macd_rule_strength", "REAL", "0.0"),
    ("rsi_rule_strength", "REAL", "0.0"),
    ("bollinger_rule_strength", "REAL", "0.0"),
]


class SQLiteSignalRepository(SignalRepository):
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
                CREATE TABLE IF NOT EXISTS market_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    trend TEXT NOT NULL,
                    trend_strength TEXT NOT NULL,
                    ema_signal TEXT NOT NULL,
                    macd_signal TEXT NOT NULL,
                    rsi_signal TEXT NOT NULL,
                    bollinger_signal TEXT NOT NULL,
                    trend_reason TEXT NOT NULL DEFAULT '',
                    ema_reason TEXT NOT NULL DEFAULT '',
                    macd_reason TEXT NOT NULL DEFAULT '',
                    rsi_reason TEXT NOT NULL DEFAULT '',
                    bollinger_reason TEXT NOT NULL DEFAULT '',
                    trend_rule_strength REAL NOT NULL DEFAULT 0.0,
                    ema_rule_strength REAL NOT NULL DEFAULT 0.0,
                    macd_rule_strength REAL NOT NULL DEFAULT 0.0,
                    rsi_rule_strength REAL NOT NULL DEFAULT 0.0,
                    bollinger_rule_strength REAL NOT NULL DEFAULT 0.0,
                    score REAL NOT NULL,
                    confidence TEXT NOT NULL,
                    signal_type TEXT NOT NULL DEFAULT 'Neutral',
                    generated_at TEXT NOT NULL
                )
                """
            )
            self._migrate_missing_columns(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_missing_columns(self, conn: sqlite3.Connection) -> None:
        """Migra bases de datos creadas con versiones anteriores de
        market_signals (sin las columnas *_reason, signal_type y/o
        *_rule_strength), sin perder ni alterar ningún registro existente.

        Idempotente: si ya se ejecutó antes (las columnas ya existen), no
        hace nada. Se puede llamar en cada arranque del bot sin riesgo.
        """
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(market_signals)")}
        for column, sql_type, default in _MIGRATION_COLUMNS:
            if column not in existing_columns:
                conn.execute(
                    f"ALTER TABLE market_signals ADD COLUMN {column} {sql_type} NOT NULL DEFAULT {default}"
                )

    def save(self, snapshot: SignalSnapshot) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                f"""
                INSERT INTO market_signals ({', '.join(_COLUMNS)})
                VALUES ({', '.join(['?'] * len(_COLUMNS))})
                """,
                (
                    snapshot.exchange,
                    snapshot.symbol,
                    snapshot.trend.value,
                    snapshot.trend_strength.value,
                    snapshot.ema_signal.value,
                    snapshot.macd_signal.value,
                    snapshot.rsi_signal.value,
                    snapshot.bollinger_signal.value,
                    snapshot.trend_reason,
                    snapshot.ema_reason,
                    snapshot.macd_reason,
                    snapshot.rsi_reason,
                    snapshot.bollinger_reason,
                    snapshot.trend_rule_strength,
                    snapshot.ema_rule_strength,
                    snapshot.macd_rule_strength,
                    snapshot.rsi_rule_strength,
                    snapshot.bollinger_rule_strength,
                    snapshot.score,
                    snapshot.confidence.value,
                    snapshot.signal_type.value,
                    snapshot.generated_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_latest(self, exchange: str, symbol: str) -> Optional[SignalSnapshot]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM market_signals "
                "WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT 1",
                (exchange, symbol),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        return self._row_to_snapshot(row) if row else None

    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[SignalSnapshot]:
        conn = self._get_connection()
        try:
            if limit is None:
                cursor = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM market_signals "
                    "WHERE exchange = ? AND symbol = ? ORDER BY id ASC",
                    (exchange, symbol),
                )
                rows = cursor.fetchall()
            else:
                cursor = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM market_signals "
                    "WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT ?",
                    (exchange, symbol, limit),
                )
                rows = list(reversed(cursor.fetchall()))
        finally:
            conn.close()

        return [self._row_to_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_snapshot(row) -> SignalSnapshot:
        return SignalSnapshot(
            exchange=row[0],
            symbol=row[1],
            trend=row[2],
            trend_strength=row[3],
            ema_signal=row[4],
            macd_signal=row[5],
            rsi_signal=row[6],
            bollinger_signal=row[7],
            trend_reason=row[8],
            ema_reason=row[9],
            macd_reason=row[10],
            rsi_reason=row[11],
            bollinger_reason=row[12],
            trend_rule_strength=row[13],
            ema_rule_strength=row[14],
            macd_rule_strength=row[15],
            rsi_rule_strength=row[16],
            bollinger_rule_strength=row[17],
            score=row[18],
            confidence=row[19],
            signal_type=row[20],
            generated_at=row[21],
        )
