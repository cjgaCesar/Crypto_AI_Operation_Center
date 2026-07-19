"""
Pruebas para src/ai/decision_engine.py.

DecisionEngine es lógica pura: no sabe leer de SQLite ni de Binance, solo
conoce un PromptBuilder y un AIProvider (inyectados). Se usa un
AIProvider falso para verificar exactamente qué recibe (el prompt) y cómo
transforma su respuesta en una AIRecommendation completa, sin depender de
DummyProvider ni de ninguna implementación real.
"""

import time

import pytest

from src.ai.base import AIProvider, AIProviderResponse
from src.ai.context import build_market_context
from src.ai.decision_engine import DecisionEngine
from src.ai.prompt_builder import CURRENT_PROMPT_VERSION, PromptBuilder, PromptVersion
from src.ai.recommendation import RecommendationAction, RiskLevel

SYSTEM_PROMPT = "Eres un analista de mercado."


class FakeProvider(AIProvider):
    def __init__(self, response: AIProviderResponse = None, exception: Exception = None, sleep_seconds: float = 0.0):
        self.response = response
        self.exception = exception
        self.sleep_seconds = sleep_seconds
        self.received_prompts = []
        self.call_count = 0

    def generate(self, prompt: str) -> AIProviderResponse:
        self.call_count += 1
        self.received_prompts.append(prompt)
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)
        if self.exception is not None:
            raise self.exception
        return self.response


class CountingPromptBuilder(PromptBuilder):
    """Envuelve el PromptBuilder real, contando cuántas veces se llama
    build(), para verificar que DecisionEngine lo invoca exactamente una vez."""

    def __init__(self):
        super().__init__()
        self.call_count = 0

    def build(self, context, system_prompt: str) -> str:
        self.call_count += 1
        return super().build(context, system_prompt)


def _response(**overrides) -> AIProviderResponse:
    defaults = dict(
        recommendation=RecommendationAction.BUY, confidence=80.0, risk_level=RiskLevel.LOW,
        reasoning="Razón de prueba.", advantages=["Ventaja"], risks=["Riesgo"],
        summary="Resumen.", model="fake-model", raw_response=None,
    )
    defaults.update(overrides)
    return AIProviderResponse(**defaults)


def _context(**overrides):
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", current_price=100.0,
        indicators=None, latest_signal=None, recent_signals=[],
    )
    defaults.update(overrides)
    return build_market_context(**defaults)


def test_decide_calls_prompt_builder_exactly_once():
    provider = FakeProvider(_response())
    prompt_builder = CountingPromptBuilder()
    engine = DecisionEngine(provider, prompt_builder, SYSTEM_PROMPT)

    engine.decide(_context())

    assert prompt_builder.call_count == 1


def test_decide_calls_provider_generate_exactly_once():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    engine.decide(_context())

    assert provider.call_count == 1


def test_decide_passes_built_prompt_to_provider():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    engine.decide(_context())

    assert len(provider.received_prompts) == 1
    assert SYSTEM_PROMPT in provider.received_prompts[0]
    assert "Symbol: BTCUSDT" in provider.received_prompts[0]


def test_decide_maps_all_provider_response_fields_into_recommendation():
    provider = FakeProvider(_response(
        recommendation=RecommendationAction.SELL, confidence=42.5, risk_level=RiskLevel.HIGH,
        reasoning="Motivo", advantages=["A1", "A2"], risks=["R1"], summary="S", model="fake-model-x",
        raw_response="raw text",
    ))
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.recommendation == RecommendationAction.SELL
    assert recommendation.confidence == 42.5
    assert recommendation.risk_level == RiskLevel.HIGH
    assert recommendation.reasoning == "Motivo"
    assert recommendation.advantages == ["A1", "A2"]
    assert recommendation.risks == ["R1"]
    assert recommendation.summary == "S"
    assert recommendation.model == "fake-model-x"
    assert recommendation.raw_response == "raw text"


def test_decide_fills_exchange_symbol_from_context():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    context = _context(symbol="ETHUSDT")
    recommendation = engine.decide(context)

    assert recommendation.exchange == "Binance"
    assert recommendation.symbol == "ETHUSDT"


def test_decide_sets_a_utc_timestamp():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.timestamp is not None
    assert recommendation.timestamp.tzinfo is not None


def test_decide_sets_provider_name_from_provider_class():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.provider == "FakeProvider"


def test_decide_sets_current_prompt_version():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.prompt_version == PromptVersion.V1
    assert recommendation.prompt_version == CURRENT_PROMPT_VERSION


def test_decide_computes_a_non_negative_processing_time():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.processing_time_ms >= 0.0


def test_decide_processing_time_reflects_provider_latency():
    provider = FakeProvider(_response(), sleep_seconds=0.05)
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    # Tolerancia amplia por la resolución del temporizador de Windows.
    assert recommendation.processing_time_ms >= 30.0


def test_decide_copies_raw_response_none():
    provider = FakeProvider(_response(raw_response=None))
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.raw_response is None


def test_decide_copies_raw_response_text():
    provider = FakeProvider(_response(raw_response="respuesta cruda del proveedor"))
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    recommendation = engine.decide(_context())

    assert recommendation.raw_response == "respuesta cruda del proveedor"


def test_decide_does_not_mutate_market_context():
    provider = FakeProvider(_response())
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    context = _context()
    context_copy = context.model_copy(deep=True)

    engine.decide(context)

    assert context == context_copy


def test_decide_propagates_provider_exceptions():
    class ProviderError(RuntimeError):
        pass

    provider = FakeProvider(exception=ProviderError("fallo simulado del proveedor"))
    engine = DecisionEngine(provider, PromptBuilder(), SYSTEM_PROMPT)

    with pytest.raises(ProviderError):
        engine.decide(_context())
