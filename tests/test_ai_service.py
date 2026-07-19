"""
Pruebas para src/ai/service.py (AIService).

Igual que SignalService (ver tests/test_signals_service.py), AIService
depende de interfaces (MarketDataRepository, IndicatorRepository,
SignalRepository, AIRepository) y de un DecisionEngine, así que se pueden
usar implementaciones falsas en las pruebas, sin tocar red ni disco ni
llamar a ningún proveedor de IA real.
"""

from datetime import datetime, timezone

from src.ai.context import MarketContext
from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.ai.repository import AIRepository
from src.ai.service import AIService
from src.database.base import IndicatorRepository, MarketDataRepository
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.base import SignalRepository
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)


class FakeMarketDataRepository(MarketDataRepository):
    def __init__(self, tickers_by_symbol=None):
        self._tickers_by_symbol = tickers_by_symbol or {}

    def init(self):
        pass

    def save(self, tickers):
        pass

    def fetch_all(self):
        return []

    def fetch_by_symbol(self, exchange, symbol, limit=None):
        tickers = self._tickers_by_symbol.get(symbol, [])
        return tickers[-limit:] if limit is not None else tickers


class FakeIndicatorRepository(IndicatorRepository):
    def __init__(self, latest_by_symbol=None):
        self._latest_by_symbol = latest_by_symbol or {}

    def init(self):
        pass

    def save(self, snapshot):
        pass

    def fetch_latest(self, exchange, symbol):
        return self._latest_by_symbol.get(symbol)

    def fetch_history(self, exchange, symbol, limit=None):
        return []


class FakeSignalRepository(SignalRepository):
    def __init__(self, latest_by_symbol=None, history_by_symbol=None):
        self._latest_by_symbol = latest_by_symbol or {}
        self._history_by_symbol = history_by_symbol or {}

    def init(self):
        pass

    def save(self, snapshot):
        pass

    def fetch_latest(self, exchange, symbol):
        return self._latest_by_symbol.get(symbol)

    def fetch_history(self, exchange, symbol, limit=None):
        history = self._history_by_symbol.get(symbol, [])
        return history[-limit:] if limit is not None else history


class FakeAIRepository(AIRepository):
    def __init__(self):
        self.saved = []

    def init(self):
        pass

    def save(self, recommendation):
        self.saved.append(recommendation)

    def fetch_latest(self, exchange, symbol):
        matches = [r for r in self.saved if r.symbol == symbol]
        return matches[-1] if matches else None

    def fetch_history(self, exchange, symbol, limit=None):
        matches = [r for r in self.saved if r.symbol == symbol]
        return matches[-limit:] if limit is not None else matches


class FakeDecisionEngine:
    """Motor falso: devuelve una AIRecommendation fija (o lanza si no se
    espera que se llame), y registra con qué MarketContext fue invocado."""

    def __init__(self, recommendation_by_symbol=None):
        self._recommendation_by_symbol = recommendation_by_symbol or {}
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        return self._recommendation_by_symbol[context.symbol]


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


def _signal(symbol="BTCUSDT", tag="r") -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance", symbol=symbol,
        trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
        rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
        trend_reason=tag, ema_reason="r", macd_reason="r", rsi_reason="r", bollinger_reason="r",
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
        processing_time_ms=10.0, raw_response=None,
    )


def test_run_cycle_saves_recommendation_when_signal_and_price_available():
    market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT", price=109.0)]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository({"BTCUSDT": _signal("BTCUSDT")})
    ai_repository = FakeAIRepository()
    engine = FakeDecisionEngine({"BTCUSDT": _recommendation("BTCUSDT")})

    service = AIService(
        market_repository=market_repository, indicator_repository=indicator_repository,
        signal_repository=signal_repository, ai_repository=ai_repository,
        decision_engine=engine, exchange="Binance", symbols=["BTCUSDT"],
    )
    service.run_cycle()

    assert len(ai_repository.saved) == 1
    assert ai_repository.saved[0].symbol == "BTCUSDT"


def test_run_cycle_skips_symbol_without_signal_yet():
    market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT")]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository({})  # sin señal todavía
    ai_repository = FakeAIRepository()
    engine = FakeDecisionEngine({})

    service = AIService(
        market_repository, indicator_repository, signal_repository, ai_repository,
        engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    assert ai_repository.saved == []
    assert engine.contexts == []


def test_run_cycle_skips_symbol_without_price_yet():
    market_repository = FakeMarketDataRepository({})  # sin historial de precios
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository({"BTCUSDT": _signal("BTCUSDT")})
    ai_repository = FakeAIRepository()
    engine = FakeDecisionEngine({"BTCUSDT": _recommendation("BTCUSDT")})

    service = AIService(
        market_repository, indicator_repository, signal_repository, ai_repository,
        engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    assert ai_repository.saved == []
    assert engine.contexts == []


def test_run_cycle_builds_context_with_price_indicators_and_signal():
    ticker = _ticker("BTCUSDT", price=123.45)
    indicators = _indicators("BTCUSDT")
    signal = _signal("BTCUSDT")
    market_repository = FakeMarketDataRepository({"BTCUSDT": [ticker]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": indicators})
    signal_repository = FakeSignalRepository({"BTCUSDT": signal})
    ai_repository = FakeAIRepository()
    engine = FakeDecisionEngine({"BTCUSDT": _recommendation("BTCUSDT")})

    service = AIService(
        market_repository, indicator_repository, signal_repository, ai_repository,
        engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    assert len(engine.contexts) == 1
    context = engine.contexts[0]
    assert context.exchange == "Binance"
    assert context.symbol == "BTCUSDT"
    assert context.current_price == 123.45
    assert context.indicators == indicators
    assert context.latest_signal == signal


def test_run_cycle_excludes_latest_signal_from_recent_signals_history():
    older_signal = _signal("BTCUSDT")
    latest_signal = _signal("BTCUSDT")
    market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT")]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository(
        latest_by_symbol={"BTCUSDT": latest_signal},
        history_by_symbol={"BTCUSDT": [older_signal, latest_signal]},
    )
    ai_repository = FakeAIRepository()
    engine = FakeDecisionEngine({"BTCUSDT": _recommendation("BTCUSDT")})

    service = AIService(
        market_repository, indicator_repository, signal_repository, ai_repository,
        engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    context = engine.contexts[0]
    assert context.recent_signals == [older_signal]


def test_run_cycle_processes_multiple_symbols_independently():
    market_repository = FakeMarketDataRepository({
        "BTCUSDT": [_ticker("BTCUSDT", price=100.0)],
        "ETHUSDT": [_ticker("ETHUSDT", price=50.0)],
    })
    indicator_repository = FakeIndicatorRepository({
        "BTCUSDT": _indicators("BTCUSDT"), "ETHUSDT": _indicators("ETHUSDT"),
    })
    signal_repository = FakeSignalRepository({
        "BTCUSDT": _signal("BTCUSDT"), "ETHUSDT": _signal("ETHUSDT"),
    })
    ai_repository = FakeAIRepository()
    engine = FakeDecisionEngine({
        "BTCUSDT": _recommendation("BTCUSDT"), "ETHUSDT": _recommendation("ETHUSDT"),
    })

    service = AIService(
        market_repository, indicator_repository, signal_repository, ai_repository,
        engine, "Binance", ["BTCUSDT", "ETHUSDT"],
    )
    service.run_cycle()

    assert len(ai_repository.saved) == 2
    assert {r.symbol for r in ai_repository.saved} == {"BTCUSDT", "ETHUSDT"}


class TestRecentSignalsHistory:
    """Cubre en detalle history = fetch_history(limit=6); recent_signals =
    history[:-1] (src/ai/service.py), para varios tamaños de historial."""

    @staticmethod
    def _run_and_get_context(history: list) -> MarketContext:
        latest_signal = history[-1]
        market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT")]})
        indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
        signal_repository = FakeSignalRepository(
            latest_by_symbol={"BTCUSDT": latest_signal},
            history_by_symbol={"BTCUSDT": history},
        )
        ai_repository = FakeAIRepository()
        engine = FakeDecisionEngine({"BTCUSDT": _recommendation("BTCUSDT")})

        service = AIService(
            market_repository, indicator_repository, signal_repository, ai_repository,
            engine, "Binance", ["BTCUSDT"],
        )
        service.run_cycle()

        return engine.contexts[0]

    def test_single_signal_yields_empty_recent_signals(self):
        only_signal = _signal(tag="s1")

        context = self._run_and_get_context([only_signal])

        assert context.latest_signal is only_signal
        assert context.recent_signals == []

    def test_fewer_than_six_signals_returns_all_previous_ones(self):
        # 3 señales totales: 2 anteriores + la última.
        history = [_signal(tag=f"s{i}") for i in range(3)]

        context = self._run_and_get_context(history)

        assert context.recent_signals == history[:-1]
        assert context.latest_signal == history[-1]

    def test_exactly_six_signals_returns_the_five_previous_ones(self):
        history = [_signal(tag=f"s{i}") for i in range(6)]

        context = self._run_and_get_context(history)

        assert len(context.recent_signals) == 5
        assert context.recent_signals == history[:-1]

    def test_more_than_six_signals_respects_the_limit_of_five_previous(self):
        # 8 señales totales: solo deben quedar las últimas 5 ANTERIORES a
        # la más reciente (no las 7 anteriores completas).
        history = [_signal(tag=f"s{i}") for i in range(8)]

        context = self._run_and_get_context(history)

        assert len(context.recent_signals) == 5
        assert context.recent_signals == history[-6:-1]
        assert context.latest_signal == history[-1]

    def test_recent_signals_are_ordered_oldest_to_newest(self):
        history = [_signal(tag=f"s{i}") for i in range(8)]

        context = self._run_and_get_context(history)

        tags = [s.trend_reason for s in context.recent_signals]
        assert tags == sorted(tags)  # "s2".."s6" ya vienen en orden ascendente

    def test_latest_signal_never_appears_inside_recent_signals(self):
        history = [_signal(tag=f"s{i}") for i in range(8)]

        context = self._run_and_get_context(history)

        assert context.latest_signal not in context.recent_signals
