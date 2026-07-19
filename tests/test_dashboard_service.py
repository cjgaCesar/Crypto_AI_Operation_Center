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

    def get_available_symbols(self):
        return self.symbols

    def get_table_status(self):
        if self.raise_on_table_status:
            raise RuntimeError("fallo simulado del repositorio")
        return self.status

    def get_latest_market(self, exchange, symbol):
        if self.raise_on_latest_market:
            raise RuntimeError("fallo simulado del repositorio")
        return self.latest_market.get((exchange, symbol))

    def get_latest_indicators(self, exchange, symbol):
        return self.latest_indicators.get((exchange, symbol))

    def get_latest_signal(self, exchange, symbol):
        return self.latest_signal.get((exchange, symbol))

    def get_latest_ai_recommendation(self, exchange, symbol):
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
