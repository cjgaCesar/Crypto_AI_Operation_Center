"""
Implementación de AIRepository usando SQLite.

Guarda las recomendaciones de IA en una tabla nueva e independiente,
'ai_recommendations', sin modificar 'market_data', 'market_indicators' ni
'market_signals'. Sigue el mismo patrón que SQLiteSignalRepository
(src/signals/sqlite_repository.py): las columnas son exactamente los
campos de AIRecommendation, sin lógica de negocio en esta clase.

Se guardan todos los campos del modelo (incluyendo 'advantages', 'risks',
'prompt_version', 'processing_time_ms' y 'raw_response', más allá del
listado mínimo pedido originalmente), por la misma razón documentada en la
Etapa 3 para 'reason'/'rule_strength': son justamente los campos de
explicabilidad y auditoría que esta etapa pide — omitirlos al guardar los
perdería para siempre.

'advantages' y 'risks' son listas de texto (list[str]): se serializan como
JSON en una columna TEXT (json.dumps al guardar, json.loads al leer), la
forma estándar de guardar una lista en una columna plana sin inventar un
formato de texto propio.

'prompt_version' es un Enum (PromptVersion): se serializa explícitamente a
texto (.value) al guardar, y Pydantic lo reconstruye como PromptVersion al
leer la fila de vuelta (igual que 'recommendation'/'risk_level').

'raw_response' es NULLABLE (Optional[str]): sqlite3 traduce None <-> NULL
automáticamente, sin necesitar ninguna conversión manual.

Migración: la tabla se creó por primera vez sin 'processing_time_ms' ni
'raw_response'. _migrate_missing_columns() agrega ambas columnas si faltan
(idempotente, mismo patrón que SQLiteSignalRepository), sin perder ni
alterar ningún registro existente.
"""

import json
from pathlib import Path
import sqlite3
from typing import Optional

from src.ai.recommendation import AIRecommendation
from src.ai.repository import AIRepository

_COLUMNS = (
    "exchange", "symbol", "recommendation", "confidence", "risk_level",
    "reasoning", "advantages", "risks", "summary",
    "provider", "model", "prompt_version",
    "processing_time_ms", "raw_response", "created_at",
)

# Columnas agregadas después de la primera versión de la tabla, con la
# definición SQL completa a usar en ALTER TABLE ... ADD COLUMN. Cada tupla
# es (columna, definición_sql). 'raw_response' es nullable (sin NOT NULL):
# no tiene un valor por defecto razonable distinto de NULL.
_MIGRATION_COLUMNS = [
    ("processing_time_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("raw_response", "TEXT"),
]


class SQLiteAIRepository(AIRepository):
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
                CREATE TABLE IF NOT EXISTS ai_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    advantages TEXT NOT NULL,
                    risks TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    processing_time_ms REAL NOT NULL DEFAULT 0.0,
                    raw_response TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._migrate_missing_columns(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_missing_columns(self, conn: sqlite3.Connection) -> None:
        """Migra bases de datos creadas con la primera versión de
        ai_recommendations (sin 'processing_time_ms' ni 'raw_response'),
        sin perder ni alterar ningún registro existente.

        Idempotente: si ya se ejecutó antes (las columnas ya existen), no
        hace nada. Se puede llamar en cada arranque del bot sin riesgo.
        """
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_recommendations)")}
        for column, definition in _MIGRATION_COLUMNS:
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE ai_recommendations ADD COLUMN {column} {definition}")

    def save(self, recommendation: AIRecommendation) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                f"""
                INSERT INTO ai_recommendations ({', '.join(_COLUMNS)})
                VALUES ({', '.join(['?'] * len(_COLUMNS))})
                """,
                (
                    recommendation.exchange,
                    recommendation.symbol,
                    recommendation.recommendation.value,
                    recommendation.confidence,
                    recommendation.risk_level.value,
                    recommendation.reasoning,
                    json.dumps(recommendation.advantages),
                    json.dumps(recommendation.risks),
                    recommendation.summary,
                    recommendation.provider,
                    recommendation.model,
                    recommendation.prompt_version.value,
                    recommendation.processing_time_ms,
                    recommendation.raw_response,
                    recommendation.timestamp.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_latest(self, exchange: str, symbol: str) -> Optional[AIRecommendation]:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM ai_recommendations "
                "WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT 1",
                (exchange, symbol),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        return self._row_to_recommendation(row) if row else None

    def fetch_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None
    ) -> list[AIRecommendation]:
        conn = self._get_connection()
        try:
            if limit is None:
                cursor = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM ai_recommendations "
                    "WHERE exchange = ? AND symbol = ? ORDER BY id ASC",
                    (exchange, symbol),
                )
                rows = cursor.fetchall()
            else:
                cursor = conn.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM ai_recommendations "
                    "WHERE exchange = ? AND symbol = ? ORDER BY id DESC LIMIT ?",
                    (exchange, symbol, limit),
                )
                rows = list(reversed(cursor.fetchall()))
        finally:
            conn.close()

        return [self._row_to_recommendation(row) for row in rows]

    @staticmethod
    def _row_to_recommendation(row) -> AIRecommendation:
        return AIRecommendation(
            exchange=row[0],
            symbol=row[1],
            recommendation=row[2],
            confidence=row[3],
            risk_level=row[4],
            reasoning=row[5],
            advantages=json.loads(row[6]),
            risks=json.loads(row[7]),
            summary=row[8],
            provider=row[9],
            model=row[10],
            prompt_version=row[11],
            processing_time_ms=row[12],
            raw_response=row[13],
            timestamp=row[14],
        )
