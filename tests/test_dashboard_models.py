"""Pruebas para src/dashboard/models.py (modelos Pydantic puros)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.ai.recommendation import RecommendationAction, RiskLevel
from src.dashboard.models import (
    DashboardStatus,
    DashboardSummary,
    DashboardSummaryView,
    IndicatorPageView,
    IndicatorSummaryView,
    LatestAIRecommendationSnapshot,
    LatestIndicatorSnapshot,
    LatestMarketSnapshot,
    LatestSignalSnapshot,
    MarketHistoryPoint,
    MarketPageView,
    MarketSummaryView,
    SignalPageView,
    SignalSummaryView,
    TableStatus,
)
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)


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


class TestDashboardSummaryView:
    def test_builds_with_all_fields_present(self):
        now = datetime.now(timezone.utc)
        view = DashboardSummaryView(
            exchange="Binance", symbol="BTCUSDT",
            price=100.0, price_change_percent_24h=1.5, market_timestamp=now,
            signal_type=SignalType.BULLISH, signal_score=70.0,
            signal_confidence=ConfidenceLevel.MEDIUM, signal_timestamp=now,
            ai_recommendation=RecommendationAction.BUY, ai_confidence=60.0,
            ai_risk_level=RiskLevel.MEDIUM, ai_timestamp=now,
            latest_update_timestamp=now,
            has_market_data=True, has_indicator_data=False,
            has_signal_data=True, has_ai_data=True,
        )
        assert view.price == 100.0
        assert view.signal_type == SignalType.BULLISH
        assert view.ai_recommendation == RecommendationAction.BUY
        assert view.has_indicator_data is False

    def test_builds_with_all_optional_fields_none(self):
        view = DashboardSummaryView(exchange="Binance", symbol="BTCUSDT")

        assert view.price is None
        assert view.price_change_percent_24h is None
        assert view.market_timestamp is None
        assert view.signal_type is None
        assert view.signal_score is None
        assert view.signal_confidence is None
        assert view.signal_timestamp is None
        assert view.ai_recommendation is None
        assert view.ai_confidence is None
        assert view.ai_risk_level is None
        assert view.ai_timestamp is None
        assert view.latest_update_timestamp is None
        assert view.has_market_data is False
        assert view.has_indicator_data is False
        assert view.has_signal_data is False
        assert view.has_ai_data is False

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            DashboardSummaryView(exchange="Binance", symbol="")

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            DashboardSummaryView(exchange="", symbol="BTCUSDT")

    @pytest.mark.parametrize("score", [-0.01, 100.01, -50.0, 200.0])
    def test_rejects_signal_score_outside_valid_range(self, score):
        with pytest.raises(ValidationError):
            DashboardSummaryView(exchange="Binance", symbol="BTCUSDT", signal_score=score)

    @pytest.mark.parametrize("confidence", [-0.01, 100.01])
    def test_rejects_ai_confidence_outside_valid_range(self, confidence):
        with pytest.raises(ValidationError):
            DashboardSummaryView(exchange="Binance", symbol="BTCUSDT", ai_confidence=confidence)

    def test_coerces_plain_string_enums(self):
        view = DashboardSummaryView(
            exchange="Binance", symbol="BTCUSDT",
            signal_type="Bullish", ai_recommendation="Buy", ai_risk_level="Medium",
        )
        assert view.signal_type == SignalType.BULLISH
        assert view.ai_recommendation == RecommendationAction.BUY
        assert view.ai_risk_level == RiskLevel.MEDIUM


class TestMarketSummaryView:
    def test_builds_with_all_fields_present(self):
        now = datetime.now(timezone.utc)
        summary = MarketSummaryView(
            exchange="Binance", symbol="BTCUSDT",
            latest_price=110.0, previous_price=100.0, absolute_change=10.0,
            percentage_change=10.0, period_high=110.0, period_low=90.0,
            latest_timestamp=now, record_count=3, volume=500.0,
        )
        assert summary.latest_price == 110.0
        assert summary.record_count == 3

    def test_optional_fields_default_to_none_and_zero(self):
        summary = MarketSummaryView(exchange="Binance", symbol="BTCUSDT")

        assert summary.latest_price is None
        assert summary.previous_price is None
        assert summary.absolute_change is None
        assert summary.percentage_change is None
        assert summary.period_high is None
        assert summary.period_low is None
        assert summary.latest_timestamp is None
        assert summary.record_count == 0
        assert summary.volume is None

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            MarketSummaryView(exchange="Binance", symbol="")

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            MarketSummaryView(exchange="", symbol="BTCUSDT")

    def test_rejects_negative_record_count(self):
        with pytest.raises(ValidationError):
            MarketSummaryView(exchange="Binance", symbol="BTCUSDT", record_count=-1)


class TestMarketHistoryPoint:
    def test_builds_with_all_fields(self):
        now = datetime.now(timezone.utc)
        point = MarketHistoryPoint(timestamp=now, price=100.0, volume=5.0)

        assert point.timestamp == now
        assert point.price == 100.0
        assert point.volume == 5.0

    def test_requires_timestamp_price_and_volume(self):
        with pytest.raises(ValidationError):
            MarketHistoryPoint(price=100.0, volume=5.0)


class TestMarketPageView:
    def test_builds_with_data_available(self):
        now = datetime.now(timezone.utc)
        summary = MarketSummaryView(exchange="Binance", symbol="BTCUSDT", latest_price=100.0)
        history = [MarketHistoryPoint(timestamp=now, price=100.0, volume=1.0)]

        page = MarketPageView(
            symbols=["BTCUSDT", "ETHUSDT"], selected_symbol="BTCUSDT",
            summary=summary, history=history, data_available=True, message=None,
        )

        assert page.symbols == ["BTCUSDT", "ETHUSDT"]
        assert page.summary is not None
        assert len(page.history) == 1
        assert page.data_available is True
        assert page.message is None

    def test_builds_with_no_data_available(self):
        page = MarketPageView(
            symbols=["BTCUSDT"], selected_symbol="BTCUSDT",
            summary=None, history=[], data_available=False,
            message="Todavía no hay precios guardados para BTCUSDT.",
        )

        assert page.summary is None
        assert page.history == []
        assert page.data_available is False
        assert "BTCUSDT" in page.message

    def test_symbols_and_history_default_to_empty_list(self):
        page = MarketPageView(selected_symbol="BTCUSDT")

        assert page.symbols == []
        assert page.history == []

    def test_rejects_empty_selected_symbol(self):
        with pytest.raises(ValidationError):
            MarketPageView(selected_symbol="")


def _indicator_snapshot() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        exchange="Binance", symbol="BTCUSDT", sma=100.0, ema_fast=100.0, ema_medium=100.0,
        ema_slow=None, rsi=50.0, macd_line=0.0, macd_signal=0.0, macd_histogram=0.0,
        bollinger_upper=110.0, bollinger_middle=100.0, bollinger_lower=90.0, vwap=100.0,
        calculated_at=datetime.now(timezone.utc),
    )


class TestIndicatorSummaryView:
    def test_builds_with_all_fields_present(self):
        now = datetime.now(timezone.utc)
        summary = IndicatorSummaryView(
            exchange="Binance", symbol="BTCUSDT", sma=100.0, ema_fast=100.0, ema_medium=100.0,
            ema_slow=99.0, rsi=55.0, macd_line=0.1, macd_signal=0.05, macd_histogram=0.05,
            bollinger_upper=110.0, bollinger_middle=100.0, bollinger_lower=90.0, vwap=100.0,
            calculated_at=now, has_data=True,
        )
        assert summary.rsi == 55.0
        assert summary.has_data is True

    def test_optional_fields_default_to_none_and_has_data_false(self):
        summary = IndicatorSummaryView(exchange="Binance", symbol="BTCUSDT")

        assert summary.sma is None
        assert summary.ema_fast is None
        assert summary.ema_medium is None
        assert summary.ema_slow is None
        assert summary.rsi is None
        assert summary.macd_line is None
        assert summary.macd_signal is None
        assert summary.macd_histogram is None
        assert summary.bollinger_upper is None
        assert summary.bollinger_middle is None
        assert summary.bollinger_lower is None
        assert summary.vwap is None
        assert summary.calculated_at is None
        assert summary.has_data is False

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            IndicatorSummaryView(exchange="Binance", symbol="")

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            IndicatorSummaryView(exchange="", symbol="BTCUSDT")

    def test_has_no_atr_adx_or_volatility_fields(self):
        """ATR/ADX/Volatilidad no existen en market_indicators todavía
        (ver README): el modelo no debe fingir que sí, agregando campos
        siempre-None."""
        summary = IndicatorSummaryView(exchange="Binance", symbol="BTCUSDT")
        assert not hasattr(summary, "atr")
        assert not hasattr(summary, "adx")
        assert not hasattr(summary, "volatility")


class TestIndicatorPageView:
    def test_builds_with_data_available(self):
        summary = IndicatorSummaryView(exchange="Binance", symbol="BTCUSDT", rsi=50.0, has_data=True)
        history = [_indicator_snapshot()]

        page = IndicatorPageView(
            symbols=["BTCUSDT", "ETHUSDT"], selected_symbol="BTCUSDT",
            summary=summary, history=history, data_available=True, message=None,
        )

        assert page.symbols == ["BTCUSDT", "ETHUSDT"]
        assert page.summary is not None
        assert len(page.history) == 1
        assert page.data_available is True
        assert page.message is None

    def test_builds_with_no_data_available(self):
        page = IndicatorPageView(
            symbols=["BTCUSDT"], selected_symbol="BTCUSDT",
            summary=None, history=[], data_available=False,
            message="Todavía no hay indicadores calculados para BTCUSDT.",
        )

        assert page.summary is None
        assert page.history == []
        assert page.data_available is False
        assert "BTCUSDT" in page.message

    def test_symbols_and_history_default_to_empty_list(self):
        page = IndicatorPageView(selected_symbol="BTCUSDT")

        assert page.symbols == []
        assert page.history == []

    def test_rejects_empty_selected_symbol(self):
        with pytest.raises(ValidationError):
            IndicatorPageView(selected_symbol="")

    def test_history_accepts_real_indicator_snapshots(self):
        snapshot = _indicator_snapshot()
        page = IndicatorPageView(selected_symbol="BTCUSDT", history=[snapshot])

        assert page.history[0] is snapshot


def _signal_snapshot() -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance", symbol="BTCUSDT",
        trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
        rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
        trend_reason="r", ema_reason="r", macd_reason="r", rsi_reason="r", bollinger_reason="r",
        trend_rule_strength=0.5, ema_rule_strength=0.5, macd_rule_strength=0.0,
        rsi_rule_strength=0.0, bollinger_rule_strength=0.0,
        score=70.0, confidence=ConfidenceLevel.MEDIUM, signal_type=SignalType.BULLISH,
        generated_at=datetime.now(timezone.utc),
    )


class TestSignalSummaryView:
    def test_builds_with_all_fields_present(self):
        now = datetime.now(timezone.utc)
        summary = SignalSummaryView(
            exchange="Binance", symbol="BTCUSDT",
            signal_type=SignalType.BULLISH, score=70.0, confidence=ConfidenceLevel.MEDIUM,
            trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
            ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
            rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
            generated_at=now, record_count=5, has_data=True,
        )
        assert summary.signal_type == SignalType.BULLISH
        assert summary.score == 70.0
        assert summary.record_count == 5
        assert summary.has_data is True

    def test_optional_fields_default_to_none_and_has_data_false(self):
        summary = SignalSummaryView(exchange="Binance", symbol="BTCUSDT")

        assert summary.signal_type is None
        assert summary.score is None
        assert summary.confidence is None
        assert summary.trend is None
        assert summary.trend_strength is None
        assert summary.ema_signal is None
        assert summary.macd_signal is None
        assert summary.rsi_signal is None
        assert summary.bollinger_signal is None
        assert summary.generated_at is None
        assert summary.record_count == 0
        assert summary.has_data is False

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            SignalSummaryView(exchange="Binance", symbol="")

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            SignalSummaryView(exchange="", symbol="BTCUSDT")

    def test_rejects_negative_record_count(self):
        with pytest.raises(ValidationError):
            SignalSummaryView(exchange="Binance", symbol="BTCUSDT", record_count=-1)

    @pytest.mark.parametrize("score", [-0.01, 100.01])
    def test_rejects_score_outside_valid_range(self, score):
        """Mismo rango que SignalSnapshot.score (0.0-100.0): no se
        inventa un límite nuevo, se respeta el que ya define el dominio."""
        with pytest.raises(ValidationError):
            SignalSummaryView(exchange="Binance", symbol="BTCUSDT", score=score)

    def test_has_no_risk_field(self):
        """'risk' no existe en market_signals (vive en ai_recommendations,
        una tabla/página distinta): el modelo no debe fingir que sí."""
        summary = SignalSummaryView(exchange="Binance", symbol="BTCUSDT")
        assert not hasattr(summary, "risk")


class TestSignalPageView:
    def test_builds_with_data_available(self):
        summary = SignalSummaryView(
            exchange="Binance", symbol="BTCUSDT", score=70.0, has_data=True,
        )
        history = [_signal_snapshot()]

        page = SignalPageView(
            symbols=["BTCUSDT", "ETHUSDT"], selected_symbol="BTCUSDT",
            summary=summary, history=history, data_available=True, message=None,
        )

        assert page.symbols == ["BTCUSDT", "ETHUSDT"]
        assert page.summary is not None
        assert len(page.history) == 1
        assert page.data_available is True
        assert page.message is None

    def test_builds_with_no_data_available(self):
        page = SignalPageView(
            symbols=["BTCUSDT"], selected_symbol="BTCUSDT",
            summary=None, history=[], data_available=False,
            message="Todavía no hay señales generadas para BTCUSDT.",
        )

        assert page.summary is None
        assert page.history == []
        assert page.data_available is False
        assert "BTCUSDT" in page.message

    def test_symbols_and_history_default_to_empty_list(self):
        page = SignalPageView(selected_symbol="BTCUSDT")

        assert page.symbols == []
        assert page.history == []

    def test_rejects_empty_selected_symbol(self):
        with pytest.raises(ValidationError):
            SignalPageView(selected_symbol="")

    def test_history_accepts_real_signal_snapshots(self):
        snapshot = _signal_snapshot()
        page = SignalPageView(selected_symbol="BTCUSDT", history=[snapshot])

        assert page.history[0] is snapshot
