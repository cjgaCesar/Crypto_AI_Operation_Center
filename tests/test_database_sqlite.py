"""
Pruebas para src/database/sqlite_repository.py.

Usa un archivo de base de datos temporal (proporcionado por pytest a través
de 'tmp_path') para no tocar nunca la base de datos real del proyecto.
"""

from datetime import datetime, timezone
import sqlite3

from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.market_data import MarketTicker


def _ticker(symbol="BTCUSDT", **overrides) -> MarketTicker:
    data = {
        "exchange": "Binance",
        "symbol": symbol,
        "price": 64822.25,
        "volume_24h": 8552.12,
        "price_change_percent_24h": 1.33,
        "queried_at": datetime(2026, 7, 19, 2, 48, 12, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return MarketTicker(**data)


def test_init_creates_file(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()
    assert (tmp_path / "test.db").exists()


def test_save_and_fetch_single_ticker(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()

    repo.save([_ticker()])

    rows = repo.fetch_all()
    assert len(rows) == 1
    assert isinstance(rows[0], MarketTicker)
    assert rows[0].exchange == "Binance"
    assert rows[0].symbol == "BTCUSDT"
    assert rows[0].price == 64822.25


def test_save_multiple_tickers(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()

    repo.save([_ticker("BTCUSDT"), _ticker("ETHUSDT")])

    rows = repo.fetch_all()
    assert len(rows) == 2
    assert rows[0].symbol == "BTCUSDT"
    assert rows[1].symbol == "ETHUSDT"


def test_save_empty_list_does_nothing(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()

    repo.save([])

    assert repo.fetch_all() == []


def test_init_is_idempotent(tmp_path):
    """Llamar init() varias veces no debe borrar datos existentes."""
    db_path = str(tmp_path / "test.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()
    repo.save([_ticker()])

    repo.init()  # Se vuelve a llamar, como haría el bot al reiniciar.

    assert len(repo.fetch_all()) == 1


def test_save_and_fetch_ticker_from_other_exchange(tmp_path):
    """El repositorio no asume Binance: guarda y lee el exchange tal cual
    viene en el MarketTicker (relevante quando se agreguen otros exchanges)."""
    db_path = str(tmp_path / "test.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()

    repo.save([_ticker(exchange="Bybit")])

    rows = repo.fetch_all()
    assert rows[0].exchange == "Bybit"


def test_init_migrates_legacy_table_without_exchange_column(tmp_path):
    """Simula una base de datos creada con la primera versión de la Etapa
    1.5 (sin columna 'exchange') y confirma que init() la migra
    automáticamente sin perder los registros existentes.
    """
    db_path = str(tmp_path / "legacy.db")

    # Se crea a mano una tabla "vieja", igual a la que existía antes de
    # agregar la columna exchange, con un registro ya guardado.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            volume_24h REAL NOT NULL,
            price_change_percent_24h REAL NOT NULL,
            queried_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO market_data (symbol, price, volume_24h, price_change_percent_24h, queried_at) "
        "VALUES ('BTCUSDT', 64822.25, 8552.12, 1.33, '2026-07-19T02:48:12+00:00')"
    )
    conn.commit()
    conn.close()

    repo = SQLiteMarketDataRepository(db_path)
    repo.init()  # Debe detectar que falta la columna 'exchange' y agregarla.

    rows = repo.fetch_all()
    assert len(rows) == 1  # El registro anterior no se perdió.
    assert rows[0].symbol == "BTCUSDT"
    assert rows[0].exchange == "Binance"  # Valor por defecto para datos históricos.

    # La base de datos migrada debe seguir aceptando escrituras normales.
    repo.save([_ticker("ETHUSDT")])
    assert len(repo.fetch_all()) == 2
