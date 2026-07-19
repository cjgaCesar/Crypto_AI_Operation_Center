"""
Prueba de garantía de solo lectura para SQLiteDashboardRepository (Etapa 5,
Iteración 5.2, Bloque 13).

Confirma explícitamente que el Dashboard no puede escribir: no crea
tablas, no cambia el conteo de registros al ejecutar sus consultas, y no
expone ningún método público de escritura (save/insert/update/delete/init).
"""

import sqlite3
from datetime import datetime, timezone

from src.dashboard.repository import DashboardRepository, SQLiteDashboardRepository
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.market_data import MarketTicker


def _ticker(symbol="BTCUSDT") -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol=symbol, price=100.0, volume_24h=1.0,
        price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
    )


def _table_names(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _row_counts(db_path: str, tables: set) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


def test_dashboard_repository_never_creates_tables(tmp_path):
    db_path = str(tmp_path / "readonly.db")
    market_repository = SQLiteMarketDataRepository(db_path)
    market_repository.init()
    market_repository.save([_ticker()])

    tables_before = _table_names(db_path)

    dashboard_repository = SQLiteDashboardRepository(db_path)
    dashboard_repository.get_available_symbols()
    dashboard_repository.get_table_status()
    dashboard_repository.get_latest_market("Binance", "BTCUSDT")
    dashboard_repository.get_market_history("Binance", "BTCUSDT", limit=10)
    dashboard_repository.get_latest_signal("Binance", "BTCUSDT")  # tabla ni siquiera existe
    dashboard_repository.get_ai_history("Binance", "BTCUSDT", limit=10)  # tabla ni siquiera existe

    tables_after = _table_names(db_path)
    assert tables_after == tables_before


def test_dashboard_repository_never_changes_row_counts(tmp_path):
    db_path = str(tmp_path / "readonly.db")
    market_repository = SQLiteMarketDataRepository(db_path)
    market_repository.init()
    market_repository.save([_ticker(), _ticker(), _ticker()])

    tables = _table_names(db_path)
    counts_before = _row_counts(db_path, tables)

    dashboard_repository = SQLiteDashboardRepository(db_path)
    for _ in range(5):  # repetir varias veces: ninguna consulta debe tener efectos secundarios
        dashboard_repository.get_available_symbols()
        dashboard_repository.get_table_status()
        dashboard_repository.get_latest_market("Binance", "BTCUSDT")
        dashboard_repository.get_market_history("Binance", "BTCUSDT", limit=10)

    counts_after = _row_counts(db_path, tables)
    assert counts_after == counts_before


def test_dashboard_repository_does_not_expose_write_methods():
    public_methods = {
        name for name in dir(SQLiteDashboardRepository)
        if not name.startswith("_") and callable(getattr(SQLiteDashboardRepository, name))
    }
    forbidden = {"save", "insert", "update", "delete", "init"}
    assert public_methods.isdisjoint(forbidden)


def test_dashboard_repository_interface_does_not_declare_write_methods():
    public_methods = {
        name for name in dir(DashboardRepository)
        if not name.startswith("_") and callable(getattr(DashboardRepository, name))
    }
    forbidden = {"save", "insert", "update", "delete", "init"}
    assert public_methods.isdisjoint(forbidden)


def test_dashboard_repository_survives_missing_database_without_creating_it(tmp_path):
    db_path = tmp_path / "does_not_exist_yet.db"
    dashboard_repository = SQLiteDashboardRepository(str(db_path))

    dashboard_repository.get_available_symbols()
    dashboard_repository.get_table_status()
    dashboard_repository.get_latest_market("Binance", "BTCUSDT")

    assert not db_path.exists()


def test_readonly_connection_actually_rejects_writes(tmp_path):
    """Confirma que _get_readonly_connection() abre el archivo en modo
    'mode=ro' de verdad (no solo de nombre): un INTENTO de escritura a
    través de esa misma conexión debe ser rechazado por SQLite, no solo
    'nunca usado para escribir' por convención de código."""
    db_path = str(tmp_path / "readonly_uri.db")
    market_repository = SQLiteMarketDataRepository(db_path)
    market_repository.init()

    dashboard_repository = SQLiteDashboardRepository(db_path)
    conn = dashboard_repository._get_readonly_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO market_data "
                "(exchange, symbol, price, volume_24h, price_change_percent_24h, queried_at) "
                "VALUES ('Binance', 'BTCUSDT', 1.0, 1.0, 1.0, '2026-01-01T00:00:00+00:00')"
            )
            conn.commit()
            wrote_successfully = True
        except sqlite3.OperationalError:
            wrote_successfully = False
    finally:
        conn.close()

    assert wrote_successfully is False


def test_dashboard_never_triggers_a_migration_on_legacy_schema(tmp_path):
    """Confirma que consultar una tabla con un esquema antiguo (le falta
    una columna que SQLiteSignalRepository migraría en un ALTER TABLE) a
    través del Dashboard NO dispara ninguna migración: la columna sigue
    faltando después, porque SQLiteDashboardRepository nunca llama a
    init() de ningún repositorio."""
    db_path = str(tmp_path / "legacy_signals.db")
    conn = sqlite3.connect(db_path)
    # Esquema deliberadamente incompleto: sin 'trend_reason' ni las demás
    # columnas que SQLiteSignalRepository.init() agregaría con su
    # migración idempotente si se le llamara.
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
    conn.commit()
    conn.close()

    columns_before = {
        row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(market_signals)")
    }
    assert "trend_reason" not in columns_before  # confirma el punto de partida "legacy"

    dashboard_repository = SQLiteDashboardRepository(db_path)
    # Ninguno de estos métodos debe intentar migrar nada; get_latest_signal
    # puede incluso fallar internamente al reconstruir SignalSnapshot (por
    # las columnas faltantes) y el propio SQLiteSignalRepository ya la
    # captura como sqlite3.OperationalError -> None, sin migrar.
    dashboard_repository.get_table_status()
    dashboard_repository.get_latest_signal("Binance", "BTCUSDT")

    columns_after = {
        row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(market_signals)")
    }
    assert columns_after == columns_before  # ninguna columna nueva: no hubo migración
