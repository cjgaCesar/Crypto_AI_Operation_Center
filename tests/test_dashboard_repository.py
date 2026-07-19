"""
Pruebas para src/dashboard/repository.py (DashboardRepository /
SQLiteDashboardRepository).

Usa los repositorios reales de las Etapas 1-4 para poblar una base SQLite
temporal (tmp_path), y verifica que SQLiteDashboardRepository la lea
correctamente sin escribir nada, incluyendo los casos de base inexistente,
tabla inexistente y tabla vacía.
"""

from datetime import datetime, timezone

from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.ai.sqlite_repository import SQLiteAIRepository
from src.dashboard.repository import SQLiteDashboardRepository
from src.database.sqlite_indicator_repository import SQLiteIndicatorRepository
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)
from src.signals.sqlite_repository import SQLiteSignalRepository


def _ticker(symbol="BTCUSDT", price=100.0) -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol=symbol, price=price, volume_24h=1.0,
        price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
    )


def _indicators(symbol="BTCUSDT") -> IndicatorSnapshot:
    return IndicatorSnapshot(
        exchange="Binance", symbol=symbol, sma=100.0, ema_fast=100.0, ema_medium=100.0,
        ema_slow=100.0, rsi=50.0, macd_line=0.0, macd_signal=0.0, macd_histogram=0.0,
        bollinger_upper=110.0, bollinger_middle=100.0, bollinger_lower=90.0, vwap=100.0,
        calculated_at=datetime.now(timezone.utc),
    )


def _signal(symbol="BTCUSDT") -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance", symbol=symbol,
        trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
        rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
        trend_reason="r", ema_reason="r", macd_reason="r", rsi_reason="r", bollinger_reason="r",
        trend_rule_strength=0.5, ema_rule_strength=0.5, macd_rule_strength=0.0,
        rsi_rule_strength=0.0, bollinger_rule_strength=0.0,
        score=70.0, confidence=ConfidenceLevel.MEDIUM, signal_type=SignalType.BULLISH,
        generated_at=datetime.now(timezone.utc),
    )


def _recommendation(symbol="BTCUSDT") -> AIRecommendation:
    return AIRecommendation(
        exchange="Binance", symbol=symbol, timestamp=datetime.now(timezone.utc),
        recommendation=RecommendationAction.BUY, confidence=60.0, risk_level=RiskLevel.MEDIUM,
        reasoning="r", advantages=["a"], risks=["b"], summary="s",
        provider="DummyProvider", model="dummy-v1", prompt_version="v1",
        processing_time_ms=1.0, raw_response=None,
    )


class TestNonExistentDatabase:
    def test_get_available_symbols_returns_empty_list(self, tmp_path):
        repo = SQLiteDashboardRepository(str(tmp_path / "no_existe.db"))
        assert repo.get_available_symbols() == []

    def test_get_table_status_reports_database_does_not_exist(self, tmp_path):
        repo = SQLiteDashboardRepository(str(tmp_path / "no_existe.db"))
        status = repo.get_table_status()
        assert status.database_exists is False
        assert all(not table.exists for table in status.tables)

    def test_get_latest_market_returns_none(self, tmp_path):
        repo = SQLiteDashboardRepository(str(tmp_path / "no_existe.db"))
        assert repo.get_latest_market("Binance", "BTCUSDT") is None

    def test_get_market_history_returns_empty_list(self, tmp_path):
        repo = SQLiteDashboardRepository(str(tmp_path / "no_existe.db"))
        assert repo.get_market_history("Binance", "BTCUSDT", limit=10) == []

    def test_does_not_create_the_database_file(self, tmp_path):
        db_path = tmp_path / "no_existe.db"
        repo = SQLiteDashboardRepository(str(db_path))

        repo.get_available_symbols()
        repo.get_table_status()
        repo.get_latest_market("Binance", "BTCUSDT")
        repo.get_market_history("Binance", "BTCUSDT", limit=10)

        assert not db_path.exists()


class TestExistingDatabaseWithMissingTables:
    def test_missing_table_reports_not_exists(self, tmp_path):
        db_path = str(tmp_path / "partial.db")
        # Solo se inicializa market_data; las otras 3 tablas no existen.
        SQLiteMarketDataRepository(db_path).init()

        repo = SQLiteDashboardRepository(db_path)
        status = repo.get_table_status()

        assert status.database_exists is True
        by_name = {t.table_name: t for t in status.tables}
        assert by_name["market_data"].exists is True
        assert by_name["market_indicators"].exists is False
        assert by_name["market_signals"].exists is False
        assert by_name["ai_recommendations"].exists is False

    def test_missing_signal_table_returns_none_for_latest_signal(self, tmp_path):
        db_path = str(tmp_path / "partial.db")
        SQLiteMarketDataRepository(db_path).init()

        repo = SQLiteDashboardRepository(db_path)
        assert repo.get_latest_signal("Binance", "BTCUSDT") is None
        assert repo.get_signal_history("Binance", "BTCUSDT", limit=10) == []

    def test_ai_disabled_scenario_missing_ai_table_returns_none(self, tmp_path):
        """Simula ai.enabled=false: las 3 tablas anteriores existen, pero
        ai_recommendations nunca se creó (ver src/main.py, build_services())."""
        db_path = str(tmp_path / "ai_disabled.db")
        SQLiteMarketDataRepository(db_path).init()
        SQLiteIndicatorRepository(db_path).init()
        SQLiteSignalRepository(db_path).init()

        repo = SQLiteDashboardRepository(db_path)
        assert repo.get_latest_ai_recommendation("Binance", "BTCUSDT") is None
        assert repo.get_ai_history("Binance", "BTCUSDT", limit=10) == []

        status = repo.get_table_status()
        by_name = {t.table_name: t for t in status.tables}
        assert by_name["ai_recommendations"].exists is False
        assert by_name["market_signals"].exists is True


class TestEmptyTables:
    def test_empty_table_reports_zero_rows_and_no_timestamp(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        SQLiteMarketDataRepository(db_path).init()

        repo = SQLiteDashboardRepository(db_path)
        status = repo.get_table_status()
        market_data_status = next(t for t in status.tables if t.table_name == "market_data")

        assert market_data_status.exists is True
        assert market_data_status.row_count == 0
        assert market_data_status.latest_timestamp is None

    def test_get_available_symbols_is_empty_when_no_rows(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        SQLiteMarketDataRepository(db_path).init()

        repo = SQLiteDashboardRepository(db_path)
        assert repo.get_available_symbols() == []


class TestPopulatedDatabase:
    def _build_populated_db(self, tmp_path) -> str:
        db_path = str(tmp_path / "populated.db")

        market_repository = SQLiteMarketDataRepository(db_path)
        market_repository.init()
        market_repository.save([_ticker("BTCUSDT", price=100.0)])
        market_repository.save([_ticker("BTCUSDT", price=101.0)])
        market_repository.save([_ticker("ETHUSDT", price=50.0)])

        indicator_repository = SQLiteIndicatorRepository(db_path)
        indicator_repository.init()
        indicator_repository.save(_indicators("BTCUSDT"))

        signal_repository = SQLiteSignalRepository(db_path)
        signal_repository.init()
        signal_repository.save(_signal("BTCUSDT"))

        ai_repository = SQLiteAIRepository(db_path)
        ai_repository.init()
        ai_repository.save(_recommendation("BTCUSDT"))

        return db_path

    def test_get_available_symbols_returns_all_distinct_symbols(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        assert repo.get_available_symbols() == ["BTCUSDT", "ETHUSDT"]

    def test_get_table_status_reports_correct_row_counts(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        status = repo.get_table_status()
        by_name = {t.table_name: t for t in status.tables}

        assert by_name["market_data"].row_count == 3
        assert by_name["market_indicators"].row_count == 1
        assert by_name["market_signals"].row_count == 1
        assert by_name["ai_recommendations"].row_count == 1
        assert all(t.exists for t in status.tables)
        assert all(t.latest_timestamp is not None for t in status.tables)

    def test_get_latest_market_returns_the_most_recent_row(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        latest = repo.get_latest_market("Binance", "BTCUSDT")
        assert latest is not None
        assert latest.price == 101.0

    def test_get_latest_indicators_signal_and_ai_return_data(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        assert repo.get_latest_indicators("Binance", "BTCUSDT") is not None
        assert repo.get_latest_signal("Binance", "BTCUSDT") is not None
        assert repo.get_latest_ai_recommendation("Binance", "BTCUSDT") is not None

    def test_symbol_without_any_data_returns_none(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        assert repo.get_latest_market("Binance", "SOLUSDT") is None
        assert repo.get_latest_signal("Binance", "SOLUSDT") is None

    def test_market_history_orders_oldest_to_newest(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        history = repo.get_market_history("Binance", "BTCUSDT", limit=10)
        assert [t.price for t in history] == [100.0, 101.0]

    def test_market_history_respects_limit(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        history = repo.get_market_history("Binance", "BTCUSDT", limit=1)
        assert len(history) == 1
        assert history[0].price == 101.0

    def test_history_is_isolated_by_symbol(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        repo = SQLiteDashboardRepository(db_path)

        btc_history = repo.get_market_history("Binance", "BTCUSDT", limit=10)
        eth_history = repo.get_market_history("Binance", "ETHUSDT", limit=10)

        assert {t.symbol for t in btc_history} == {"BTCUSDT"}
        assert {t.symbol for t in eth_history} == {"ETHUSDT"}

    def test_history_is_isolated_by_exchange(self, tmp_path):
        db_path = self._build_populated_db(tmp_path)
        market_repository = SQLiteMarketDataRepository(db_path)
        market_repository.save([_ticker("BTCUSDT", price=999.0)])  # exchange default "Binance"

        repo = SQLiteDashboardRepository(db_path)
        other_exchange_history = repo.get_market_history("OtroExchange", "BTCUSDT", limit=10)

        assert other_exchange_history == []
