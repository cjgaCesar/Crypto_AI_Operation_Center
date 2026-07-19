"""
Pruebas para src/ai/sqlite_repository.py (SQLiteAIRepository) y, de forma
indirecta, para la interfaz src/ai/repository.py (AIRepository): esta clase
es la única implementación real hoy, así que probarla cubre el contrato
completo (init/save/fetch_latest/fetch_history), incluyendo la migración
desde el esquema anterior a 'processing_time_ms'/'raw_response'.
"""

import sqlite3
from datetime import datetime, timezone

from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.ai.prompt_builder import PromptVersion
from src.ai.sqlite_repository import SQLiteAIRepository


def _recommendation(symbol="BTCUSDT", **overrides) -> AIRecommendation:
    defaults = dict(
        exchange="Binance", symbol=symbol, timestamp=datetime.now(timezone.utc),
        recommendation=RecommendationAction.BUY, confidence=70.0, risk_level=RiskLevel.MEDIUM,
        reasoning="Razón de prueba.", advantages=["Ventaja 1", "Ventaja 2"], risks=["Riesgo 1"],
        summary="Resumen de prueba.", provider="DummyProvider", model="dummy-v1",
        prompt_version=PromptVersion.V1, processing_time_ms=15.5, raw_response=None,
    )
    defaults.update(overrides)
    return AIRecommendation(**defaults)


def test_init_creates_ai_recommendations_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    repository = SQLiteAIRepository(db_path)

    repository.init()

    conn = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()
    assert "ai_recommendations" in tables


def test_init_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    repository = SQLiteAIRepository(db_path)

    repository.init()
    repository.init()
    repository.init()  # 3 llamadas consecutivas, sin error.


def test_fetch_latest_returns_none_when_empty(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    assert repository.fetch_latest("Binance", "BTCUSDT") is None


def test_save_and_fetch_latest_roundtrip(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()
    recommendation = _recommendation()

    repository.save(recommendation)
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched is not None
    assert fetched.exchange == "Binance"
    assert fetched.symbol == "BTCUSDT"
    assert fetched.recommendation == RecommendationAction.BUY
    assert fetched.confidence == 70.0
    assert fetched.risk_level == RiskLevel.MEDIUM
    assert fetched.reasoning == "Razón de prueba."
    assert fetched.advantages == ["Ventaja 1", "Ventaja 2"]
    assert fetched.risks == ["Riesgo 1"]
    assert fetched.summary == "Resumen de prueba."
    assert fetched.provider == "DummyProvider"
    assert fetched.model == "dummy-v1"
    assert fetched.prompt_version == PromptVersion.V1
    assert fetched.processing_time_ms == 15.5
    assert fetched.raw_response is None


def test_fetch_latest_returns_the_most_recent_of_several(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(summary="Primera"))
    repository.save(_recommendation(summary="Segunda"))
    repository.save(_recommendation(summary="Tercera"))

    latest = repository.fetch_latest("Binance", "BTCUSDT")
    assert latest.summary == "Tercera"


def test_fetch_history_returns_oldest_to_newest(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(summary="Primera"))
    repository.save(_recommendation(summary="Segunda"))
    repository.save(_recommendation(summary="Tercera"))

    history = repository.fetch_history("Binance", "BTCUSDT")
    assert [r.summary for r in history] == ["Primera", "Segunda", "Tercera"]


def test_fetch_history_respects_limit(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    for i in range(5):
        repository.save(_recommendation(summary=f"Recomendación {i}"))

    history = repository.fetch_history("Binance", "BTCUSDT", limit=2)
    assert [r.summary for r in history] == ["Recomendación 3", "Recomendación 4"]


def test_recommendations_are_isolated_by_symbol(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(symbol="BTCUSDT", summary="BTC"))
    repository.save(_recommendation(symbol="ETHUSDT", summary="ETH"))

    btc_latest = repository.fetch_latest("Binance", "BTCUSDT")
    eth_latest = repository.fetch_latest("Binance", "ETHUSDT")

    assert btc_latest.summary == "BTC"
    assert eth_latest.summary == "ETH"


def test_recommendations_are_isolated_by_exchange(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(exchange="Binance", summary="Binance-rec"))
    repository.save(_recommendation(exchange="OtroExchange", summary="Otro-rec"))

    binance_latest = repository.fetch_latest("Binance", "BTCUSDT")
    otro_latest = repository.fetch_latest("OtroExchange", "BTCUSDT")

    assert binance_latest.summary == "Binance-rec"
    assert otro_latest.summary == "Otro-rec"


def test_empty_advantages_and_risks_roundtrip_correctly(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(advantages=[], risks=[]))
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched.advantages == []
    assert fetched.risks == []


def test_advantages_and_risks_with_special_characters_roundtrip_as_json(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(
        advantages=['Ventaja con "comillas" y, coma'], risks=["Riesgo con salto\nde línea"],
    ))
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched.advantages == ['Ventaja con "comillas" y, coma']
    assert fetched.risks == ["Riesgo con salto\nde línea"]


def test_enums_roundtrip_correctly(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(
        recommendation=RecommendationAction.STRONG_SELL, risk_level=RiskLevel.VERY_HIGH,
    ))
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched.recommendation == RecommendationAction.STRONG_SELL
    assert fetched.risk_level == RiskLevel.VERY_HIGH
    assert fetched.prompt_version == PromptVersion.V1


def test_processing_time_ms_roundtrips_correctly(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(processing_time_ms=123.456))
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched.processing_time_ms == 123.456


def test_raw_response_none_roundtrips_as_none(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    repository.save(_recommendation(raw_response=None))
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched.raw_response is None


def test_raw_response_with_text_roundtrips_exactly(tmp_path):
    repository = SQLiteAIRepository(str(tmp_path / "test.db"))
    repository.init()

    raw = '{"id": "abc123", "choices": [{"text": "Buy"}]}'
    repository.save(_recommendation(raw_response=raw))
    fetched = repository.fetch_latest("Binance", "BTCUSDT")

    assert fetched.raw_response == raw


def test_migration_adds_processing_time_ms_and_raw_response_without_losing_existing_rows(tmp_path):
    """Simula una base de datos creada con la primera versión de
    ai_recommendations (sin 'processing_time_ms' ni 'raw_response'),
    inserta un registro con ese esquema antiguo, y confirma que init()
    migra las columnas faltantes sin perder el registro existente,
    aplicando los valores por defecto correctos, y que la migración es
    completamente idempotente (3 llamadas consecutivas a init())."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE ai_recommendations (
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
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO ai_recommendations (
            exchange, symbol, recommendation, confidence, risk_level, reasoning,
            advantages, risks, summary, provider, model, prompt_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Binance", "BTCUSDT", "Buy", 55.0, "Low", "Razón antigua",
            '["Ventaja antigua"]', '["Riesgo antiguo"]', "Resumen antiguo",
            "DummyProvider", "dummy-v1", "v1", "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()

    repository = SQLiteAIRepository(db_path)

    # 1ra ejecución: debe migrar (agregar las 2 columnas faltantes).
    repository.init()

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_recommendations)")}
    conn.close()
    assert "processing_time_ms" in columns
    assert "raw_response" in columns

    # El registro antiguo sigue intacto, con los valores por defecto aplicados.
    legacy = repository.fetch_latest("Binance", "BTCUSDT")
    assert legacy is not None
    assert legacy.summary == "Resumen antiguo"
    assert legacy.advantages == ["Ventaja antigua"]
    assert legacy.risks == ["Riesgo antiguo"]
    assert legacy.processing_time_ms == 0.0
    assert legacy.raw_response is None

    # 2da ejecución: debe ser un no-op (idempotente).
    repository.init()
    # 3ra ejecución: sigue sin errores.
    repository.init()

    conn = sqlite3.connect(db_path)
    column_names = [row[1] for row in conn.execute("PRAGMA table_info(ai_recommendations)")]
    row_count = conn.execute("SELECT COUNT(*) FROM ai_recommendations").fetchone()[0]
    conn.close()

    # No se duplican columnas ni se pierden registros.
    assert column_names.count("processing_time_ms") == 1
    assert column_names.count("raw_response") == 1
    assert row_count == 1

    # Un registro nuevo (post-migración) funciona con normalidad.
    repository.save(_recommendation(symbol="ETHUSDT", processing_time_ms=42.0, raw_response="cruda"))
    new_record = repository.fetch_latest("Binance", "ETHUSDT")
    assert new_record.processing_time_ms == 42.0
    assert new_record.raw_response == "cruda"
