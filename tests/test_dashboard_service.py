"""
Pruebas para src/dashboard/service.py (DashboardService).

Usa un FakeDashboardRepository (mismo patrón que las Fakes de
tests/test_signals_service.py y tests/test_ai_service.py) para probar la
lógica del Service sin tocar SQLite.
"""

from datetime import datetime, timezone

import pytest

from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.dashboard.models import DashboardStatus, TableStatus
from src.dashboard.repository import DashboardRepository
from src.dashboard.service import DashboardService
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)


class FakeDashboardRepository(DashboardRepository):
    def __init__(self):
        self.symbols = []
        self.status = DashboardStatus(database_path="data/x.db", database_exists=True, tables=[])
        self.latest_market = {}
        self.latest_indicators = {}
        self.latest_signal = {}
        self.latest_ai = {}
        self.market_history = {}
        self.indicator_history = {}
        self.signal_history = {}
        self.ai_history = {}
        self.raise_on_table_status = False
        self.raise_on_latest_market = False
        self.call_counts = {"market": 0, "indicators": 0, "signal": 0, "ai": 0}

    def get_available_symbols(self):
        return self.symbols

    def get_table_status(self):
        if self.raise_on_table_status:
            raise RuntimeError("fallo simulado del repositorio")
        return self.status

    def get_latest_market(self, exchange, symbol):
        self.call_counts["market"] += 1
        if self.raise_on_latest_market:
            raise RuntimeError("fallo simulado del repositorio")
        return self.latest_market.get((exchange, symbol))

    def get_latest_indicators(self, exchange, symbol):
        self.call_counts["indicators"] += 1
        return self.latest_indicators.get((exchange, symbol))

    def get_latest_signal(self, exchange, symbol):
        self.call_counts["signal"] += 1
        return self.latest_signal.get((exchange, symbol))

    def get_latest_ai_recommendation(self, exchange, symbol):
        self.call_counts["ai"] += 1
        return self.latest_ai.get((exchange, symbol))

    def get_market_history(self, exchange, symbol, limit):
        return self.market_history.get((exchange, symbol), [])[-limit:]

    def get_indicator_history(self, exchange, symbol, limit):
        return self.indicator_history.get((exchange, symbol), [])[-limit:]

    def get_signal_history(self, exchange, symbol, limit):
        return self.signal_history.get((exchange, symbol), [])[-limit:]

    def get_ai_history(self, exchange, symbol, limit):
        return self.ai_history.get((exchange, symbol), [])[-limit:]


def _ticker(symbol="BTCUSDT") -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol=symbol, price=100.0, volume_24h=1.0,
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


def _service(repository=None) -> DashboardService:
    return DashboardService(
        repository=repository or FakeDashboardRepository(),
        exchange="Binance", symbols=["BTCUSDT", "ETHUSDT"],
        default_history_limit=100, max_history_limit=1000,
    )


def test_get_system_status_delegates_to_repository():
    repository = FakeDashboardRepository()
    service = _service(repository)

    assert service.get_system_status() is repository.status


def test_get_summary_returns_one_entry_per_configured_symbol():
    service = _service()
    summaries = service.get_summary()

    assert [s.symbol for s in summaries] == ["BTCUSDT", "ETHUSDT"]


def test_get_symbol_summary_includes_data_when_available():
    repository = FakeDashboardRepository()
    repository.latest_market[("Binance", "BTCUSDT")] = _ticker()
    repository.latest_signal[("Binance", "BTCUSDT")] = _signal()
    service = _service(repository)

    summary = service.get_symbol_summary("Binance", "BTCUSDT")

    assert summary.market.ticker is not None
    assert summary.signal.signal is not None
    assert summary.indicators.indicators is None
    assert summary.ai_recommendation.recommendation is None


def test_get_symbol_summary_normalizes_symbol_and_exchange():
    service = _service()
    summary = service.get_symbol_summary("  binance  ", "btcusdt")

    assert summary.exchange == "binance"
    assert summary.symbol == "BTCUSDT"


def test_get_market_view_returns_history_from_repository():
    repository = FakeDashboardRepository()
    repository.market_history[("Binance", "BTCUSDT")] = [_ticker(), _ticker()]
    service = _service(repository)

    view = service.get_market_view("Binance", "BTCUSDT", limit=10)
    assert len(view) == 2


def test_get_indicators_view_returns_empty_when_no_history():
    service = _service()
    assert service.get_indicators_view("Binance", "BTCUSDT") == []


def test_get_signals_view_and_ai_view_return_empty_when_no_history():
    service = _service()
    assert service.get_signals_view("Binance", "BTCUSDT") == []
    assert service.get_ai_view("Binance", "BTCUSDT") == []


def test_limit_is_clamped_to_maximum():
    repository = FakeDashboardRepository()
    repository.market_history[("Binance", "BTCUSDT")] = [_ticker() for _ in range(5)]
    service = DashboardService(
        repository=repository, exchange="Binance", symbols=["BTCUSDT"],
        default_history_limit=100, max_history_limit=3,
    )

    view = service.get_market_view("Binance", "BTCUSDT", limit=1000)
    assert len(view) <= 3


def test_none_limit_uses_default_history_limit():
    repository = FakeDashboardRepository()
    repository.market_history[("Binance", "BTCUSDT")] = [_ticker() for _ in range(2)]
    service = DashboardService(
        repository=repository, exchange="Binance", symbols=["BTCUSDT"],
        default_history_limit=1, max_history_limit=1000,
    )

    view = service.get_market_view("Binance", "BTCUSDT", limit=None)
    assert len(view) == 1


def test_repository_exception_on_table_status_is_handled_gracefully():
    repository = FakeDashboardRepository()
    repository.raise_on_table_status = True
    service = _service(repository)

    status = service.get_system_status()

    assert status.database_exists is False


def test_repository_exception_on_latest_market_is_handled_gracefully():
    repository = FakeDashboardRepository()
    repository.raise_on_latest_market = True
    service = _service(repository)

    summary = service.get_symbol_summary("Binance", "BTCUSDT")

    assert summary.market.ticker is None


class TestGetSummaryView:
    def test_returns_one_view_per_configured_symbol(self):
        service = _service()
        views = service.get_summary_view()

        assert [v.symbol for v in views] == ["BTCUSDT", "ETHUSDT"]

    def test_view_includes_flattened_market_and_signal_fields(self):
        repository = FakeDashboardRepository()
        repository.latest_market[("Binance", "BTCUSDT")] = _ticker("BTCUSDT")
        repository.latest_signal[("Binance", "BTCUSDT")] = _signal("BTCUSDT")
        service = _service(repository)

        view = service.get_summary_view()[0]

        assert view.price == 100.0
        assert view.signal_type == SignalType.BULLISH
        assert view.signal_score == 70.0
        assert view.signal_confidence == ConfidenceLevel.MEDIUM
        assert view.has_market_data is True
        assert view.has_signal_data is True
        assert view.has_indicator_data is False
        assert view.has_ai_data is False

    def test_view_includes_ai_fields_when_available(self):
        repository = FakeDashboardRepository()
        repository.latest_ai[("Binance", "BTCUSDT")] = _recommendation("BTCUSDT")
        service = _service(repository)

        view = service.get_summary_view()[0]

        assert view.ai_recommendation == RecommendationAction.BUY
        assert view.ai_confidence == 60.0
        assert view.ai_risk_level == RiskLevel.MEDIUM
        assert view.has_ai_data is True

    def test_latest_update_timestamp_is_the_maximum_of_the_four_sources(self):
        oldest = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newest = datetime(2026, 1, 3, tzinfo=timezone.utc)
        middle = datetime(2026, 1, 2, tzinfo=timezone.utc)

        repository = FakeDashboardRepository()
        repository.latest_market[("Binance", "BTCUSDT")] = MarketTicker(
            exchange="Binance", symbol="BTCUSDT", price=100.0, volume_24h=1.0,
            price_change_percent_24h=1.0, queried_at=oldest,
        )
        repository.latest_signal[("Binance", "BTCUSDT")] = SignalSnapshot(
            exchange="Binance", symbol="BTCUSDT",
            trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
            ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
            rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
            trend_reason="r", ema_reason="r", macd_reason="r", rsi_reason="r", bollinger_reason="r",
            trend_rule_strength=0.5, ema_rule_strength=0.5, macd_rule_strength=0.0,
            rsi_rule_strength=0.0, bollinger_rule_strength=0.0,
            score=70.0, confidence=ConfidenceLevel.MEDIUM, signal_type=SignalType.BULLISH,
            generated_at=middle,
        )
        repository.latest_ai[("Binance", "BTCUSDT")] = AIRecommendation(
            exchange="Binance", symbol="BTCUSDT", timestamp=newest,
            recommendation=RecommendationAction.BUY, confidence=60.0, risk_level=RiskLevel.MEDIUM,
            reasoning="r", advantages=["a"], risks=["b"], summary="s",
            provider="DummyProvider", model="dummy-v1", prompt_version="v1",
            processing_time_ms=1.0, raw_response=None,
        )
        service = _service(repository)

        view = service.get_summary_view()[0]

        assert view.latest_update_timestamp == newest

    def test_latest_update_timestamp_is_none_without_any_data(self):
        service = _service()
        view = service.get_summary_view()[0]

        assert view.latest_update_timestamp is None

    def test_market_available_without_signal(self):
        repository = FakeDashboardRepository()
        repository.latest_market[("Binance", "BTCUSDT")] = _ticker("BTCUSDT")
        service = _service(repository)

        view = service.get_summary_view()[0]

        assert view.has_market_data is True
        assert view.has_signal_data is False
        assert view.signal_type is None

    def test_signal_available_without_ai(self):
        repository = FakeDashboardRepository()
        repository.latest_signal[("Binance", "BTCUSDT")] = _signal("BTCUSDT")
        service = _service(repository)

        view = service.get_summary_view()[0]

        assert view.has_signal_data is True
        assert view.has_ai_data is False
        assert view.ai_recommendation is None

    def test_view_is_isolated_by_symbol(self):
        repository = FakeDashboardRepository()
        repository.latest_market[("Binance", "BTCUSDT")] = _ticker("BTCUSDT", )
        repository.latest_market[("Binance", "ETHUSDT")] = MarketTicker(
            exchange="Binance", symbol="ETHUSDT", price=2000.0, volume_24h=1.0,
            price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
        )
        service = _service(repository)

        views = service.get_summary_view()

        assert views[0].symbol == "BTCUSDT" and views[0].price == 100.0
        assert views[1].symbol == "ETHUSDT" and views[1].price == 2000.0

    def test_view_is_isolated_by_exchange(self):
        repository = FakeDashboardRepository()
        repository.latest_market[("Binance", "BTCUSDT")] = _ticker("BTCUSDT")
        repository.latest_market[("OtroExchange", "BTCUSDT")] = MarketTicker(
            exchange="OtroExchange", symbol="BTCUSDT", price=999.0, volume_24h=1.0,
            price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
        )
        service = DashboardService(
            repository=repository, exchange="Binance", symbols=["BTCUSDT"],
            default_history_limit=100, max_history_limit=1000,
        )

        view = service.get_summary_view(exchange="Binance")[0]
        assert view.price == 100.0

        other_view = service.get_summary_view(exchange="OtroExchange")[0]
        assert other_view.price == 999.0

    def test_does_not_call_repository_more_times_than_necessary(self):
        repository = FakeDashboardRepository()
        service = DashboardService(
            repository=repository, exchange="Binance", symbols=["BTCUSDT", "ETHUSDT"],
            default_history_limit=100, max_history_limit=1000,
        )

        service.get_summary_view()

        # Exactamente 1 llamada por símbolo a cada una de las 4 fuentes
        # (2 símbolos configurados): ninguna llamada repetida ni de más.
        assert repository.call_counts == {"market": 2, "indicators": 2, "signal": 2, "ai": 2}


class TestGetMarketPage:
    def test_no_history_returns_unavailable_page_with_message(self):
        service = _service()
        page = service.get_market_page("Binance", "BTCUSDT")

        assert page.data_available is False
        assert page.summary is None
        assert page.history == []
        assert "BTCUSDT" in page.message

    def test_includes_configured_symbols_and_selected_symbol(self):
        repository = FakeDashboardRepository()
        repository.market_history[("Binance", "BTCUSDT")] = [_ticker("BTCUSDT")]
        service = _service(repository)

        page = service.get_market_page("Binance", "btcusdt")

        assert page.symbols == ["BTCUSDT", "ETHUSDT"]
        assert page.selected_symbol == "BTCUSDT"

    def test_single_record_has_no_previous_price_or_change(self):
        repository = FakeDashboardRepository()
        repository.market_history[("Binance", "BTCUSDT")] = [_ticker("BTCUSDT")]
        service = _service(repository)

        page = service.get_market_page("Binance", "BTCUSDT")

        assert page.data_available is True
        assert page.summary.previous_price is None
        assert page.summary.absolute_change is None
        assert page.summary.percentage_change is None
        assert page.summary.record_count == 1
        assert page.summary.period_high == 100.0
        assert page.summary.period_low == 100.0

    def test_multiple_records_compute_change_and_period_high_low(self):
        repository = FakeDashboardRepository()
        history = [
            MarketTicker(
                exchange="Binance", symbol="BTCUSDT", price=price, volume_24h=1.0,
                price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
            )
            for price in (100.0, 90.0, 110.0)
        ]
        repository.market_history[("Binance", "BTCUSDT")] = history
        service = _service(repository)

        page = service.get_market_page("Binance", "BTCUSDT")

        assert page.summary.latest_price == 110.0
        assert page.summary.previous_price == 90.0
        assert page.summary.absolute_change == 20.0
        assert page.summary.percentage_change == pytest.approx((20.0 / 90.0) * 100)
        assert page.summary.period_high == 110.0
        assert page.summary.period_low == 90.0
        assert page.summary.record_count == 3

    def test_history_points_preserve_order_and_values(self):
        repository = FakeDashboardRepository()
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        history = [
            MarketTicker(
                exchange="Binance", symbol="BTCUSDT", price=100.0, volume_24h=5.0,
                price_change_percent_24h=1.0, queried_at=t1,
            ),
            MarketTicker(
                exchange="Binance", symbol="BTCUSDT", price=105.0, volume_24h=6.0,
                price_change_percent_24h=1.0, queried_at=t2,
            ),
        ]
        repository.market_history[("Binance", "BTCUSDT")] = history
        service = _service(repository)

        page = service.get_market_page("Binance", "BTCUSDT")

        assert [p.timestamp for p in page.history] == [t1, t2]
        assert [p.price for p in page.history] == [100.0, 105.0]
        assert [p.volume for p in page.history] == [5.0, 6.0]

    def test_limit_is_resolved_like_other_history_methods(self):
        repository = FakeDashboardRepository()
        repository.market_history[("Binance", "BTCUSDT")] = [_ticker() for _ in range(5)]
        service = DashboardService(
            repository=repository, exchange="Binance", symbols=["BTCUSDT"],
            default_history_limit=100, max_history_limit=3,
        )

        page = service.get_market_page("Binance", "BTCUSDT", limit=1000)
        assert page.summary.record_count <= 3

    def test_view_is_isolated_by_exchange(self):
        repository = FakeDashboardRepository()
        repository.market_history[("Binance", "BTCUSDT")] = [_ticker("BTCUSDT")]
        repository.market_history[("OtroExchange", "BTCUSDT")] = [
            MarketTicker(
                exchange="OtroExchange", symbol="BTCUSDT", price=999.0, volume_24h=1.0,
                price_change_percent_24h=1.0, queried_at=datetime.now(timezone.utc),
            )
        ]
        service = _service(repository)

        page = service.get_market_page("Binance", "BTCUSDT")
        other_page = service.get_market_page("OtroExchange", "BTCUSDT")

        assert page.summary.latest_price == 100.0
        assert other_page.summary.latest_price == 999.0

    def test_repository_exception_is_handled_gracefully(self):
        class RaisingRepository(FakeDashboardRepository):
            def get_market_history(self, exchange, symbol, limit):
                raise RuntimeError("fallo simulado del repositorio")

        service = _service(RaisingRepository())
        page = service.get_market_page("Binance", "BTCUSDT")

        assert page.data_available is False
        assert page.summary is None
