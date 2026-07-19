"""
Pruebas para src/signals/sqlite_repository.py.

Usa un archivo de base de datos temporal (proporcionado por pytest a través
de 'tmp_path') para no tocar nunca la base de datos real del proyecto.
"""

from datetime import datetime, timezone
import sqlite3

from src.signals.sqlite_repository import SQLiteSignalRepository
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel,
    ConfidenceLevel,
    EMALabel,
    MACDLabel,
    RSILabel,
    SignalType,
    TrendLabel,
    TrendStrength,
)


def _snapshot(symbol="BTCUSDT", **overrides) -> SignalSnapshot:
    data = {
        "exchange": "Binance",
        "symbol": symbol,
        "trend": TrendLabel.BULLISH,
        "trend_strength": TrendStrength.MEDIUM,
        "ema_signal": EMALabel.BULLISH,
        "macd_signal": MACDLabel.BULLISH_CROSS,
        "rsi_signal": RSILabel.NEUTRAL,
        "bollinger_signal": BollingerLabel.INSIDE_BANDS,
        "trend_reason": "EMA rápida sobre la lenta.",
        "ema_reason": "EMA rápida sobre la media.",
        "macd_reason": "MACD por encima de su señal.",
        "rsi_reason": "RSI en zona neutral.",
        "bollinger_reason": "Precio dentro de las bandas.",
        "trend_rule_strength": 0.6,
        "ema_rule_strength": 0.4,
        "macd_rule_strength": 0.3,
        "rsi_rule_strength": 0.0,
        "bollinger_rule_strength": 0.0,
        "score": 70.0,
        "confidence": ConfidenceLevel.MEDIUM,
        "signal_type": SignalType.BULLISH,
        "generated_at": datetime(2026, 7, 19, 3, 0, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return SignalSnapshot(**data)


def test_init_creates_file(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()
    assert (tmp_path / "test.db").exists()


def test_save_and_fetch_latest(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()

    repo.save(_snapshot())

    latest = repo.fetch_latest("Binance", "BTCUSDT")
    assert isinstance(latest, SignalSnapshot)
    assert latest.symbol == "BTCUSDT"
    assert latest.trend == TrendLabel.BULLISH
    assert latest.score == 70.0
    assert latest.trend_reason == "EMA rápida sobre la lenta."
    assert latest.signal_type == SignalType.BULLISH
    assert latest.trend_rule_strength == 0.6
    assert latest.ema_rule_strength == 0.4


def test_fetch_latest_returns_none_when_no_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()

    assert repo.fetch_latest("Binance", "BTCUSDT") is None


def test_fetch_latest_returns_most_recent(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()

    repo.save(_snapshot(score=50.0))
    repo.save(_snapshot(score=80.0))

    latest = repo.fetch_latest("Binance", "BTCUSDT")
    assert latest.score == 80.0


def test_fetch_history_orders_oldest_to_newest(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()

    repo.save(_snapshot(score=20.0))
    repo.save(_snapshot(score=50.0))
    repo.save(_snapshot(score=80.0))

    history = repo.fetch_history("Binance", "BTCUSDT")
    assert [h.score for h in history] == [20.0, 50.0, 80.0]


def test_fetch_history_respects_limit(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()

    for score in [20.0, 50.0, 80.0]:
        repo.save(_snapshot(score=score))

    history = repo.fetch_history("Binance", "BTCUSDT", limit=2)
    assert [h.score for h in history] == [50.0, 80.0]


def test_fetch_by_exchange_and_symbol_are_independent(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()

    repo.save(_snapshot("BTCUSDT", exchange="Binance"))
    repo.save(_snapshot("ETHUSDT", exchange="Binance"))
    repo.save(_snapshot("BTCUSDT", exchange="Bybit"))

    assert repo.fetch_latest("Binance", "BTCUSDT").symbol == "BTCUSDT"
    assert len(repo.fetch_history("Binance", "BTCUSDT")) == 1


def test_init_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteSignalRepository(db_path)
    repo.init()
    repo.save(_snapshot())

    repo.init()  # Se vuelve a llamar, como haría el bot al reiniciar.
    repo.init()  # Y una tercera vez, para confirmar que sigue sin errores.

    assert len(repo.fetch_history("Binance", "BTCUSDT")) == 1


# --- Migración completa desde el esquema más antiguo (punto 6) -------------

def _create_legacy_table_without_any_new_columns(db_path: str) -> None:
    """Simula la primera versión histórica de market_signals: sin
    *_reason, sin signal_type y sin *_rule_strength (las 3 ampliaciones que
    se agregaron en distintos momentos de la Etapa 3)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE market_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            trend TEXT NOT NULL,
            trend_strength TEXT NOT NULL,
            ema_signal TEXT NOT NULL,
            macd_signal TEXT NOT NULL,
            rsi_signal TEXT NOT NULL,
            bollinger_signal TEXT NOT NULL,
            score REAL NOT NULL,
            confidence TEXT NOT NULL,
            generated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO market_signals "
        "(exchange, symbol, trend, trend_strength, ema_signal, macd_signal, "
        "rsi_signal, bollinger_signal, score, confidence, generated_at) "
        "VALUES ('Binance', 'BTCUSDT', 'Bullish', 'Medium', 'Bullish', "
        "'Bullish Cross', 'Neutral', 'Inside Bands', 70.0, 'Medium', "
        "'2026-07-19T03:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def test_migration_adds_all_missing_columns_without_losing_existing_rows(tmp_path):
    """Prueba específica del punto 6: simula una base de datos antigua sin
    reasons, sin signal_type y sin las fuerzas individuales; ejecuta
    init() y comprueba que:
    - las columnas nuevas se agregan;
    - el registro antiguo se conserva;
    - los valores predeterminados se aplican (reason='', signal_type=
      'Neutral', *_rule_strength=0.0);
    - los registros nuevos se pueden guardar y leer con normalidad;
    - init() puede ejecutarse varias veces sin errores (idempotente).
    """
    db_path = str(tmp_path / "legacy.db")
    _create_legacy_table_without_any_new_columns(db_path)

    # Antes de migrar: confirmamos que, en efecto, faltan las columnas.
    conn = sqlite3.connect(db_path)
    columns_before = {row[1] for row in conn.execute("PRAGMA table_info(market_signals)")}
    conn.close()
    for missing in (
        "trend_reason", "ema_reason", "macd_reason", "rsi_reason", "bollinger_reason",
        "signal_type", "trend_rule_strength", "ema_rule_strength", "macd_rule_strength",
        "rsi_rule_strength", "bollinger_rule_strength",
    ):
        assert missing not in columns_before

    repo = SQLiteSignalRepository(db_path)
    repo.init()  # 1ra ejecución: debe migrar.
    repo.init()  # 2da ejecución: debe ser un no-op (idempotente).
    repo.init()  # 3ra ejecución: sigue sin errores.

    # Las columnas nuevas ahora existen.
    conn = sqlite3.connect(db_path)
    columns_after = {row[1] for row in conn.execute("PRAGMA table_info(market_signals)")}
    conn.close()
    for added in (
        "trend_reason", "ema_reason", "macd_reason", "rsi_reason", "bollinger_reason",
        "signal_type", "trend_rule_strength", "ema_rule_strength", "macd_rule_strength",
        "rsi_rule_strength", "bollinger_rule_strength",
    ):
        assert added in columns_after

    # El registro antiguo se conserva, con los valores por defecto correctos.
    history = repo.fetch_history("Binance", "BTCUSDT")
    assert len(history) == 1
    legacy_row = history[0]
    assert legacy_row.trend == TrendLabel.BULLISH
    assert legacy_row.score == 70.0
    assert legacy_row.trend_reason == ""
    assert legacy_row.ema_reason == ""
    assert legacy_row.macd_reason == ""
    assert legacy_row.rsi_reason == ""
    assert legacy_row.bollinger_reason == ""
    assert legacy_row.signal_type == SignalType.NEUTRAL
    assert legacy_row.trend_rule_strength == 0.0
    assert legacy_row.ema_rule_strength == 0.0
    assert legacy_row.macd_rule_strength == 0.0
    assert legacy_row.rsi_rule_strength == 0.0
    assert legacy_row.bollinger_rule_strength == 0.0

    # La base de datos migrada debe seguir aceptando escrituras y lecturas normales.
    repo.save(_snapshot("ETHUSDT"))
    all_rows = repo.fetch_history("Binance", "ETHUSDT")
    assert len(all_rows) == 1
    assert all_rows[0].trend_rule_strength == 0.6

    total_btc_and_eth = len(repo.fetch_history("Binance", "BTCUSDT")) + len(
        repo.fetch_history("Binance", "ETHUSDT")
    )
    assert total_btc_and_eth == 2  # 1 antiguo + 1 nuevo, ninguno se perdió
