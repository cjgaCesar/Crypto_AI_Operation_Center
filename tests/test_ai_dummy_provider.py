"""
Pruebas para src/ai/providers/dummy_provider.py.

DummyProvider es el único AIProvider realmente conectado hoy: debe ser
determinista (nunca generar texto aleatorio) y ejecutarse completamente
offline. Estas pruebas verifican su comportamiento para los 3 signal_type
posibles y para el caso sin señal, además de la simulación de latencia,
raw_response, modelo y rangos de confidence/risk_level.
"""

import time

from src.ai.base import AIProviderResponse
from src.ai.providers.dummy_provider import DummyProvider
from src.ai.recommendation import RecommendationAction, RiskLevel


def test_bullish_signal_type_returns_buy():
    response = DummyProvider().generate("...\nSignal Type: Bullish\n...")

    assert isinstance(response, AIProviderResponse)
    assert response.recommendation == RecommendationAction.BUY
    assert response.risk_level == RiskLevel.MEDIUM


def test_bearish_signal_type_returns_sell():
    response = DummyProvider().generate("...\nSignal Type: Bearish\n...")

    assert response.recommendation == RecommendationAction.SELL
    assert response.risk_level == RiskLevel.MEDIUM


def test_neutral_signal_type_returns_hold():
    response = DummyProvider().generate("...\nSignal Type: Neutral\n...")

    assert response.recommendation == RecommendationAction.HOLD
    assert response.risk_level == RiskLevel.LOW


def test_missing_signal_type_marker_returns_hold():
    response = DummyProvider().generate("Exchange: Binance\nSymbol: BTCUSDT")

    assert response.recommendation == RecommendationAction.HOLD
    assert response.risk_level == RiskLevel.LOW
    assert "Todavía no hay una señal disponible" in response.reasoning


def test_response_is_deterministic_across_repeated_calls():
    provider = DummyProvider()
    prompt = "...\nSignal Type: Bullish\n..."

    responses = [provider.generate(prompt) for _ in range(5)]

    assert all(r.recommendation == RecommendationAction.BUY for r in responses)
    assert all(r.confidence == responses[0].confidence for r in responses)
    assert all(r.reasoning == responses[0].reasoning for r in responses)


def test_same_prompt_produces_the_same_response_object_fields():
    provider = DummyProvider()
    prompt = "Signal Type: Bearish"

    first = provider.generate(prompt)
    second = provider.generate(prompt)

    assert first == second


def test_response_always_has_advantages_risks_and_summary():
    response = DummyProvider().generate("Signal Type: Bullish")

    assert len(response.advantages) >= 1
    assert len(response.risks) >= 1
    assert response.summary


def test_response_model_is_always_dummy_v1():
    for signal_type in ["Bullish", "Bearish", "Neutral"]:
        response = DummyProvider().generate(f"Signal Type: {signal_type}")
        assert response.model == "dummy-v1"


def test_response_confidence_is_within_valid_range():
    for signal_type in ["Bullish", "Bearish", "Neutral"]:
        response = DummyProvider().generate(f"Signal Type: {signal_type}")
        assert 0.0 <= response.confidence <= 100.0


def test_response_risk_level_is_a_valid_risk_level_member():
    for signal_type in ["Bullish", "Bearish", "Neutral"]:
        response = DummyProvider().generate(f"Signal Type: {signal_type}")
        assert response.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH,
                                        RiskLevel.VERY_LOW, RiskLevel.VERY_HIGH)


def test_response_raw_response_is_always_none():
    for signal_type in ["Bullish", "Bearish", "Neutral"]:
        response = DummyProvider().generate(f"Signal Type: {signal_type}")
        assert response.raw_response is None

    assert DummyProvider().generate("sin marcador alguno").raw_response is None


def test_zero_delay_does_not_wait():
    provider = DummyProvider(delay_seconds=0.0)

    start = time.monotonic()
    provider.generate("Signal Type: Neutral")
    elapsed = time.monotonic() - start

    assert elapsed < 0.05


def test_positive_delay_makes_generate_wait_at_least_that_long():
    # Delay generoso y tolerancia amplia: la resolución del temporizador de
    # Windows (~15ms) puede hacer que time.sleep() despierte unos
    # milisegundos antes de lo pedido; lo relevante es confirmar que SÍ
    # espera, no medir precisión de sub-milisegundo. Se mantiene pequeño
    # para no volver la suite de pruebas lenta.
    provider = DummyProvider(delay_seconds=0.05)

    start = time.monotonic()
    provider.generate("Signal Type: Neutral")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.03
