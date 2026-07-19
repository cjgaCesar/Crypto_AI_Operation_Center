"""
Pruebas para src/database/sqlite_indicator_repository.py.

Usa un archivo de base de datos temporal (proporcionado por pytest a través
de 'tmp_path') para no tocar nunca la base de datos real del proyecto.
"""

from datetime import datetime, timezone

from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.models.indicator_data import IndicatorSnapshot


def _snapshot(symbol="BTCUSDT", **overrides) -> IndicatorSnapshot:
    data = {
        "exchange": "Binance",
        "symbol": symbol,
        "sma": 100.0,
        "ema_fast": 101.0,
        "ema_medium": 102.0,
        "ema_slow": 103.0,
        "rsi": 55.5,
        "macd_line": 1.5,
        "macd_signal": 1.2,
        "macd_histogram": 0.3,
        "bollinger_upper": 110.0,
        "bollinger_middle": 100.0,
        "bollinger_lower": 90.0,
        "vwap": 99.5,
        "calculated_at": datetime(2026, 7, 19, 3, 0, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return IndicatorSnapshot(**data)


def test_init_creates_file(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()
    assert (tmp_path / "test.db").exists()


def test_save_and_fetch_latest(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()

    repo.save(_snapshot())

    latest = repo.fetch_latest("Binance", "BTCUSDT")
    assert isinstance(latest, IndicatorSnapshot)
    assert latest.symbol == "BTCUSDT"
    assert latest.sma == 100.0
    assert latest.rsi == 55.5


def test_fetch_latest_returns_none_when_no_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()

    assert repo.fetch_latest("Binance", "BTCUSDT") is None


def test_fetch_latest_returns_most_recent(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()

    repo.save(_snapshot(sma=100.0))
    repo.save(_snapshot(sma=200.0))

    latest = repo.fetch_latest("Binance", "BTCUSDT")
    assert latest.sma == 200.0


def test_fetch_history_orders_oldest_to_newest(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()

    repo.save(_snapshot(sma=100.0))
    repo.save(_snapshot(sma=200.0))
    repo.save(_snapshot(sma=300.0))

    history = repo.fetch_history("Binance", "BTCUSDT")
    assert [h.sma for h in history] == [100.0, 200.0, 300.0]


def test_fetch_history_respects_limit(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()

    for sma in [100.0, 200.0, 300.0]:
        repo.save(_snapshot(sma=sma))

    history = repo.fetch_history("Binance", "BTCUSDT", limit=2)
    assert [h.sma for h in history] == [200.0, 300.0]


def test_save_and_fetch_snapshot_with_none_fields(tmp_path):
    """Los campos None (indicadores todavía no calculables) deben poder
    guardarse y leerse de vuelta como None, no como error."""
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()

    repo.save(_snapshot(ema_slow=None, macd_signal=None, macd_histogram=None))

    latest = repo.fetch_latest("Binance", "BTCUSDT")
    assert latest.ema_slow is None
    assert latest.macd_signal is None
    assert latest.macd_histogram is None
    assert latest.sma == 100.0  # el resto de los campos sí llegó bien


def test_init_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    repo = SQLiteIndicatorRepository(db_path)
    repo.init()
    repo.save(_snapshot())

    repo.init()  # Se vuelve a llamar, como haría el bot al reiniciar.

    assert len(repo.fetch_history("Binance", "BTCUSDT")) == 1
