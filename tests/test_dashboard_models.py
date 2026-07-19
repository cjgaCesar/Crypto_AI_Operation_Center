"""Pruebas para src/dashboard/models.py (modelos Pydantic puros)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.dashboard.models import (
    DashboardStatus,
    DashboardSummary,
    LatestAIRecommendationSnapshot,
    LatestIndicatorSnapshot,
    LatestMarketSnapshot,
    LatestSignalSnapshot,
    TableStatus,
)
from src.models.market_data import MarketTicker


def _ticker() -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol="BTCUSDT", price=100.0, volume_24h=1.0,
        price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
    )


class TestTableStatus:
    def test_builds_with_all_fields(self):
        status = TableStatus(
            table_name="market_data", exists=True, row_count=10,
            latest_timestamp=datetime.now(timezone.utc),
        )
        assert status.exists is True
        assert status.row_count == 10

    def test_row_count_defaults_to_zero(self):
        status = TableStatus(table_name="market_data", exists=False)
        assert status.row_count == 0
        assert status.latest_timestamp is None

    def test_rejects_empty_table_name(self):
        with pytest.raises(ValidationError):
            TableStatus(table_name="", exists=False)

    def test_rejects_negative_row_count(self):
        with pytest.raises(ValidationError):
            TableStatus(table_name="market_data", exists=True, row_count=-1)


class TestDashboardStatus:
    def test_builds_with_empty_tables_list(self):
        status = DashboardStatus(database_path="data/x.db", database_exists=False)
        assert status.tables == []

    def test_builds_with_tables(self):
        tables = [TableStatus(table_name="market_data", exists=True, row_count=5)]
        status = DashboardStatus(database_path="data/x.db", database_exists=True, tables=tables)
        assert len(status.tables) == 1

    def test_rejects_empty_database_path(self):
        with pytest.raises(ValidationError):
            DashboardStatus(database_path="", database_exists=False)


class TestLatestSnapshots:
    def test_latest_market_snapshot_accepts_missing_ticker(self):
        snapshot = LatestMarketSnapshot(exchange="Binance", symbol="BTCUSDT", ticker=None)
        assert snapshot.ticker is None

    def test_latest_market_snapshot_accepts_present_ticker(self):
        ticker = _ticker()
        snapshot = LatestMarketSnapshot(exchange="Binance", symbol="BTCUSDT", ticker=ticker)
        assert snapshot.ticker == ticker

    def test_latest_indicator_snapshot_accepts_missing_indicators(self):
        snapshot = LatestIndicatorSnapshot(exchange="Binance", symbol="BTCUSDT")
        assert snapshot.indicators is None

    def test_latest_signal_snapshot_accepts_missing_signal(self):
        snapshot = LatestSignalSnapshot(exchange="Binance", symbol="BTCUSDT")
        assert snapshot.signal is None

    def test_latest_ai_recommendation_snapshot_accepts_missing_recommendation(self):
        snapshot = LatestAIRecommendationSnapshot(exchange="Binance", symbol="BTCUSDT")
        assert snapshot.recommendation is None

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            LatestMarketSnapshot(exchange="Binance", symbol="")

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            LatestMarketSnapshot(exchange="", symbol="BTCUSDT")


class TestDashboardSummary:
    def test_builds_with_all_parts_empty(self):
        summary = DashboardSummary(
            exchange="Binance", symbol="BTCUSDT",
            market=LatestMarketSnapshot(exchange="Binance", symbol="BTCUSDT"),
            indicators=LatestIndicatorSnapshot(exchange="Binance", symbol="BTCUSDT"),
            signal=LatestSignalSnapshot(exchange="Binance", symbol="BTCUSDT"),
            ai_recommendation=LatestAIRecommendationSnapshot(exchange="Binance", symbol="BTCUSDT"),
        )
        assert summary.market.ticker is None
        assert summary.signal.signal is None

    def test_builds_with_partial_data(self):
        summary = DashboardSummary(
            exchange="Binance", symbol="BTCUSDT",
            market=LatestMarketSnapshot(exchange="Binance", symbol="BTCUSDT", ticker=_ticker()),
            indicators=LatestIndicatorSnapshot(exchange="Binance", symbol="BTCUSDT"),
            signal=LatestSignalSnapshot(exchange="Binance", symbol="BTCUSDT"),
            ai_recommendation=LatestAIRecommendationSnapshot(exchange="Binance", symbol="BTCUSDT"),
        )
        assert summary.market.ticker is not None
        assert summary.indicators.indicators is None
