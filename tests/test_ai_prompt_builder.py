"""
Pruebas para src/ai/prompt_builder.py.

El prompt NO debe contener lógica de negocio: solo expone la información
que ya trae el MarketContext. Estas pruebas verifican que toda la
información relevante (precio, indicadores, señal con reasons/strength,
historial) aparezca en el texto generado, y que las secciones opcionales
se omitan quiéticamente cuando no hay datos.
"""

from datetime import datetime, timezone

from src.ai.context import build_market_context
from src.ai.prompt_builder import PromptBuilder
from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
)

SYSTEM_PROMPT = "Eres un analista de mercado de criptomonedas."


def _signal(signal_type=SignalType.BULLISH) -> SignalSnapshot:
    return SignalSnapshot(
        exchange="Binance", symbol="BTCUSDT",
        trend=TrendLabel.BULLISH, trend_strength=TrendStrength.MEDIUM,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.NEUTRAL,
        rsi_signal=RSILabel.NEUTRAL, bollinger_signal=BollingerLabel.INSIDE_BANDS,
        trend_reason="EMA rápida sobre EMA lenta.", ema_reason="EMA rápida sobre EMA media.",
        macd_reason="MACD sin cruce claro.", rsi_reason="RSI en zona neutral.",
        bollinger_reason="Precio dentro de las bandas.",
        trend_rule_strength=0.7, ema_rule_strength=0.5, macd_rule_strength=0.1,
        rsi_rule_strength=0.0, bollinger_rule_strength=0.2,
        score=75.0, confidence=ConfidenceLevel.HIGH, signal_type=signal_type,
        generated_at=datetime.now(timezone.utc),
    )


def _indicators() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        exchange="Binance", symbol="BTCUSDT", sma=100.0, ema_fast=105.0, ema_medium=102.0,
        ema_slow=98.0, rsi=55.0, macd_line=1.2, macd_signal=1.0, macd_histogram=0.2,
        bollinger_upper=110.0, bollinger_middle=100.0, bollinger_lower=90.0, vwap=101.0,
        calculated_at=datetime.now(timezone.utc),
    )


def test_prompt_includes_system_prompt_and_market_section():
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=109.0,
        indicators=None, latest_signal=None, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert SYSTEM_PROMPT in prompt
    assert "Exchange: Binance" in prompt
    assert "Symbol: BTCUSDT" in prompt
    assert "Current Price: 109.0" in prompt


def test_prompt_omits_indicators_section_when_missing():
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=None, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Indicators:" not in prompt


def test_prompt_includes_indicators_section_with_values():
    indicators = _indicators()
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=indicators, latest_signal=None, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Indicators:" in prompt
    assert "RSI: 55.0" in prompt
    assert "105.0 / 102.0 / 98.0" in prompt  # EMA fast/medium/slow


def test_prompt_includes_signal_section_with_reasons_and_strength():
    signal = _signal()
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=signal, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Latest Signal:" in prompt
    assert signal.trend_reason in prompt
    assert signal.ema_reason in prompt
    assert signal.macd_reason in prompt
    assert signal.rsi_reason in prompt
    assert signal.bollinger_reason in prompt
    assert "rule_strength: 0.70" in prompt
    assert f"Score: {signal.score:.2f}" in prompt
    assert f"Confidence: {signal.confidence.value}" in prompt
    assert "Signal Type: Bullish" in prompt


def test_prompt_omits_signal_section_when_missing():
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=None, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Latest Signal:" not in prompt


def test_prompt_includes_history_section_when_present():
    history = [_signal(), _signal()]
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=None, recent_signals=history,
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Recent Signal History" in prompt


def test_prompt_omits_history_section_when_empty():
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=None, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Recent Signal History" not in prompt


def test_prompt_reflects_bearish_signal_type():
    signal = _signal(signal_type=SignalType.BEARISH)
    context = build_market_context(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=signal, recent_signals=[],
    )
    prompt = PromptBuilder().build(context, SYSTEM_PROMPT)

    assert "Signal Type: Bearish" in prompt
