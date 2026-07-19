"""
Pruebas para src/signals/service.py.

Gracias a que el servicio depende de las interfaces MarketDataRepository,
IndicatorRepository y SignalRepository (y de un SignalEngine, no de SQLite
directamente), se pueden usar implementaciones falsas ("fakes") en las
pruebas, sin tocar red ni disco ni el motor de cálculo real.
"""

from datetime import datetime, timezone

from src.database.base import IndicatorRepository, MarketDataRepository
from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.models.signal_data import SignalSnapshot
from src.signals.base import SignalRepository
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
from src.signals.service import SignalService


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
    def __init__(self):
        self.saved = []

    def init(self):
        pass

    def save(self, snapshot):
        self.saved.append(snapshot)

    def fetch_latest(self, exchange, symbol):
        matches = [s for s in self.saved if s.symbol == symbol]
        return matches[-1] if matches else None

    def fetch_history(self, exchange, symbol, limit=None):
        matches = [s for s in self.saved if s.symbol == symbol]
        return matches[-limit:] if limit is not None else matches


class FakeSignalEngine:
    """Motor falso: devuelve una señal fija por símbolo (o None, simulando
    'sin indicadores/precio suficientes'), y registra con qué argumentos
    fue invocado, para poder verificar que SignalService le pasa los datos
    correctos sin tener que ejecutar las 5 reglas reales."""

    def __init__(self, snapshot_by_symbol=None):
        self._snapshot_by_symbol = snapshot_by_symbol or {}
        self.calls = []

    def calculate(self, exchange, symbol, indicators, price):
        self.calls.append((exchange, symbol, indicators, price))
        return self._snapshot_by_symbol.get(symbol)


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


def test_run_cycle_saves_signal_when_engine_produces_one():
    market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT", price=109.0)]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({"BTCUSDT": _signal("BTCUSDT")})

    service = SignalService(
        market_repository=market_repository,
        indicator_repository=indicator_repository,
        signal_repository=signal_repository,
        engine=engine,
        exchange="Binance",
        symbols=["BTCUSDT"],
    )
    service.run_cycle()

    assert len(signal_repository.saved) == 1
    assert signal_repository.saved[0].symbol == "BTCUSDT"


def test_run_cycle_skips_symbol_when_engine_returns_none():
    market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT")]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({})  # sin señal para BTCUSDT: simula falta de historial

    service = SignalService(
        market_repository, indicator_repository, signal_repository, engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    assert signal_repository.saved == []


def test_run_cycle_passes_latest_price_and_indicators_to_engine():
    ticker = _ticker("BTCUSDT", price=123.45)
    indicators = _indicators("BTCUSDT")
    market_repository = FakeMarketDataRepository({"BTCUSDT": [ticker]})
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": indicators})
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({"BTCUSDT": _signal("BTCUSDT")})

    service = SignalService(
        market_repository, indicator_repository, signal_repository, engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    assert len(engine.calls) == 1
    exchange, symbol, passed_indicators, passed_price = engine.calls[0]
    assert exchange == "Binance"
    assert symbol == "BTCUSDT"
    assert passed_indicators == indicators
    assert passed_price == 123.45


def test_run_cycle_passes_none_price_when_no_market_history():
    market_repository = FakeMarketDataRepository({})  # sin historial de precios
    indicator_repository = FakeIndicatorRepository({"BTCUSDT": _indicators("BTCUSDT")})
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({"BTCUSDT": _signal("BTCUSDT")})

    service = SignalService(
        market_repository, indicator_repository, signal_repository, engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    _, _, _, passed_price = engine.calls[0]
    assert passed_price is None


def test_run_cycle_passes_none_indicators_when_missing():
    market_repository = FakeMarketDataRepository({"BTCUSDT": [_ticker("BTCUSDT")]})
    indicator_repository = FakeIndicatorRepository({})  # sin indicadores todavía
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({})

    service = SignalService(
        market_repository, indicator_repository, signal_repository, engine, "Binance", ["BTCUSDT"],
    )
    service.run_cycle()

    _, _, passed_indicators, _ = engine.calls[0]
    assert passed_indicators is None


def test_run_cycle_processes_multiple_symbols_independently():
    market_repository = FakeMarketDataRepository({
        "BTCUSDT": [_ticker("BTCUSDT", price=100.0)],
        "ETHUSDT": [_ticker("ETHUSDT", price=50.0)],
    })
    indicator_repository = FakeIndicatorRepository({
        "BTCUSDT": _indicators("BTCUSDT"), "ETHUSDT": _indicators("ETHUSDT"),
    })
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({"BTCUSDT": _signal("BTCUSDT"), "ETHUSDT": _signal("ETHUSDT")})

    service = SignalService(
        market_repository, indicator_repository, signal_repository, engine,
        "Binance", ["BTCUSDT", "ETHUSDT"],
    )
    service.run_cycle()

    assert len(signal_repository.saved) == 2
    assert {s.symbol for s in signal_repository.saved} == {"BTCUSDT", "ETHUSDT"}


def test_run_cycle_with_partial_results_saves_only_the_successful_symbol():
    market_repository = FakeMarketDataRepository({
        "BTCUSDT": [_ticker("BTCUSDT")], "ETHUSDT": [_ticker("ETHUSDT")],
    })
    indicator_repository = FakeIndicatorRepository({
        "BTCUSDT": _indicators("BTCUSDT"), "ETHUSDT": _indicators("ETHUSDT"),
    })
    signal_repository = FakeSignalRepository()
    engine = FakeSignalEngine({"BTCUSDT": _signal("BTCUSDT")})  # ETHUSDT sin señal

    service = SignalService(
        market_repository, indicator_repository, signal_repository, engine,
        "Binance", ["BTCUSDT", "ETHUSDT"],
    )
    service.run_cycle()

    assert len(signal_repository.saved) == 1
    assert signal_repository.saved[0].symbol == "BTCUSDT"
