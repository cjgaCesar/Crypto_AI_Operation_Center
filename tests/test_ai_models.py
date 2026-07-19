"""
Pruebas para los modelos Pydantic de la Etapa 4 (src/ai/context.py,
recommendation.py, explanation.py, models.py, prompt_builder.py).
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.ai.context import MarketContext, build_market_context
from src.ai.explanation import AIExplanation, build_explanation
from src.ai.models import (
    AIExplanation as ReexportedAIExplanation,
    AIRecommendation as ReexportedAIRecommendation,
    MarketContext as ReexportedMarketContext,
    PromptVersion as ReexportedPromptVersion,
)
from src.ai.prompt_builder import PromptVersion
from src.ai.recommendation import AIRecommendation, RecommendationAction, RiskLevel
from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot
from src.signals.enums import (
    BollingerLabel, ConfidenceLevel, EMALabel, MACDLabel, RSILabel, SignalType, TrendLabel, TrendStrength,
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


def _indicators(symbol="BTCUSDT") -> IndicatorSnapshot:
    return IndicatorSnapshot(
        exchange="Binance", symbol=symbol, sma=100.0, ema_fast=100.0, ema_medium=100.0,
        ema_slow=100.0, rsi=50.0, macd_line=0.0, macd_signal=0.0, macd_histogram=0.0,
        bollinger_upper=110.0, bollinger_middle=100.0, bollinger_lower=90.0, vwap=100.0,
        calculated_at=datetime.now(timezone.utc),
    )


def _recommendation(**overrides) -> AIRecommendation:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", timestamp=datetime.now(timezone.utc),
        recommendation=RecommendationAction.BUY, confidence=75.0, risk_level=RiskLevel.MEDIUM,
        reasoning="Tendencia alcista confirmada por el motor de señales.",
        advantages=["Score alto", "Confidence alto"],
        risks=["Volatilidad de corto plazo"],
        summary="Comprar con precaución.",
        provider="DummyProvider", model="dummy-v1", prompt_version=PromptVersion.V1,
        processing_time_ms=12.5, raw_response=None,
    )
    defaults.update(overrides)
    return AIRecommendation(**defaults)


# --- MarketContext ----------------------------------------------------------

class TestMarketContext:
    def test_builds_with_all_fields_present(self):
        signal = _signal()
        indicators = _indicators()
        context = build_market_context(
            exchange="Binance", symbol="BTCUSDT", current_price=109.0,
            indicators=indicators, latest_signal=signal, recent_signals=[signal],
        )
        assert context.exchange == "Binance"
        assert context.symbol == "BTCUSDT"
        assert context.current_price == 109.0
        assert context.indicators == indicators
        assert context.latest_signal == signal
        assert context.recent_signals == [signal]
        assert context.generated_at is not None

    def test_allows_missing_indicators_and_signal(self):
        context = build_market_context(
            exchange="Binance", symbol="BTCUSDT", current_price=100.0,
            indicators=None, latest_signal=None, recent_signals=[],
        )
        assert context.indicators is None
        assert context.latest_signal is None
        assert context.recent_signals == []

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            MarketContext(
                exchange="Binance", symbol="", current_price=100.0,
                generated_at=datetime.now(timezone.utc),
            )

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            MarketContext(
                exchange="", symbol="BTCUSDT", current_price=100.0,
                generated_at=datetime.now(timezone.utc),
            )

    @pytest.mark.parametrize("price", [0.0, -1.0, -100.0])
    def test_rejects_current_price_not_greater_than_zero(self, price):
        with pytest.raises(ValidationError):
            MarketContext(
                exchange="Binance", symbol="BTCUSDT", current_price=price,
                generated_at=datetime.now(timezone.utc),
            )

    def test_accepts_small_positive_current_price(self):
        context = MarketContext(
            exchange="Binance", symbol="BTCUSDT", current_price=0.0001,
            generated_at=datetime.now(timezone.utc),
        )
        assert context.current_price == 0.0001


# --- RecommendationAction / RiskLevel (enums ampliados) ------------------------

class TestExpandedEnums:
    def test_recommendation_action_has_seven_values(self):
        assert len(list(RecommendationAction)) == 7

    def test_recommendation_action_preserves_original_three_values(self):
        assert RecommendationAction.BUY.value == "Buy"
        assert RecommendationAction.SELL.value == "Sell"
        assert RecommendationAction.HOLD.value == "Hold"

    def test_recommendation_action_includes_strong_and_weak_levels(self):
        assert RecommendationAction.STRONG_BUY.value == "Strong Buy"
        assert RecommendationAction.WEAK_BUY.value == "Weak Buy"
        assert RecommendationAction.WEAK_SELL.value == "Weak Sell"
        assert RecommendationAction.STRONG_SELL.value == "Strong Sell"

    def test_risk_level_has_five_values(self):
        assert len(list(RiskLevel)) == 5

    def test_risk_level_preserves_original_three_values(self):
        assert RiskLevel.LOW.value == "Low"
        assert RiskLevel.MEDIUM.value == "Medium"
        assert RiskLevel.HIGH.value == "High"

    def test_risk_level_includes_very_low_and_very_high(self):
        assert RiskLevel.VERY_LOW.value == "Very Low"
        assert RiskLevel.VERY_HIGH.value == "Very High"

    def test_existing_recommendation_built_with_original_values_still_works(self):
        # Compatibilidad: una AIRecommendation construida solo con los 3
        # valores originales (como las que ya pudo haber generado
        # DummyProvider) debe seguir siendo válida sin cambios.
        recommendation = _recommendation(
            recommendation=RecommendationAction.HOLD, risk_level=RiskLevel.LOW,
        )
        assert recommendation.recommendation == RecommendationAction.HOLD
        assert recommendation.risk_level == RiskLevel.LOW


# --- PromptVersion ---------------------------------------------------------

class TestPromptVersion:
    def test_prompt_version_v1_has_expected_value(self):
        assert PromptVersion.V1.value == "v1"

    def test_recommendation_coerces_plain_string_to_prompt_version_enum(self):
        recommendation = _recommendation(prompt_version="v1")
        assert recommendation.prompt_version == PromptVersion.V1
        assert isinstance(recommendation.prompt_version, PromptVersion)

    def test_recommendation_rejects_unknown_prompt_version(self):
        with pytest.raises(ValidationError):
            _recommendation(prompt_version="v99")


# --- AIRecommendation ---------------------------------------------------------

class TestAIRecommendation:
    def test_builds_with_valid_fields(self):
        recommendation = _recommendation()
        assert recommendation.recommendation == RecommendationAction.BUY
        assert recommendation.risk_level == RiskLevel.MEDIUM
        assert recommendation.confidence == 75.0
        assert recommendation.prompt_version == PromptVersion.V1
        assert recommendation.processing_time_ms == 12.5
        assert recommendation.raw_response is None

    @pytest.mark.parametrize("confidence", [-0.1, 100.1, -50.0, 150.0])
    def test_rejects_confidence_outside_0_100(self, confidence):
        with pytest.raises(ValidationError):
            _recommendation(confidence=confidence)

    @pytest.mark.parametrize("confidence", [0.0, 50.0, 100.0])
    def test_accepts_confidence_at_boundaries(self, confidence):
        recommendation = _recommendation(confidence=confidence)
        assert recommendation.confidence == confidence

    def test_rejects_empty_reasoning(self):
        with pytest.raises(ValidationError):
            _recommendation(reasoning="")

    def test_rejects_empty_summary(self):
        with pytest.raises(ValidationError):
            _recommendation(summary="")

    def test_rejects_empty_exchange(self):
        with pytest.raises(ValidationError):
            _recommendation(exchange="")

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValidationError):
            _recommendation(symbol="")

    def test_rejects_empty_provider(self):
        with pytest.raises(ValidationError):
            _recommendation(provider="")

    def test_rejects_empty_model(self):
        with pytest.raises(ValidationError):
            _recommendation(model="")

    def test_allows_empty_advantages_and_risks_lists(self):
        recommendation = _recommendation(advantages=[], risks=[])
        assert recommendation.advantages == []
        assert recommendation.risks == []

    def test_coerces_plain_string_action_to_enum(self):
        recommendation = _recommendation(recommendation="Sell")
        assert recommendation.recommendation == RecommendationAction.SELL
        assert isinstance(recommendation.recommendation, RecommendationAction)

    def test_rejects_invalid_action_value(self):
        with pytest.raises(ValidationError):
            _recommendation(recommendation="Maybe")

    @pytest.mark.parametrize("processing_time_ms", [-0.001, -1.0, -100.0])
    def test_rejects_negative_processing_time_ms(self, processing_time_ms):
        with pytest.raises(ValidationError):
            _recommendation(processing_time_ms=processing_time_ms)

    @pytest.mark.parametrize("processing_time_ms", [0.0, 0.5, 100.0, 5000.0])
    def test_accepts_non_negative_processing_time_ms(self, processing_time_ms):
        recommendation = _recommendation(processing_time_ms=processing_time_ms)
        assert recommendation.processing_time_ms == processing_time_ms

    def test_raw_response_defaults_to_none(self):
        recommendation = _recommendation(raw_response=None)
        assert recommendation.raw_response is None

    def test_raw_response_accepts_text(self):
        recommendation = _recommendation(raw_response='{"choices": []}')
        assert recommendation.raw_response == '{"choices": []}'


# --- AIExplanation / build_explanation ---------------------------------------

class TestAIExplanation:
    def test_build_explanation_includes_advantages_and_risks_as_bullets(self):
        recommendation = _recommendation(
            advantages=["Ventaja 1", "Ventaja 2"], risks=["Riesgo 1"],
        )
        explanation = build_explanation(recommendation)

        assert isinstance(explanation, AIExplanation)
        assert "+ Ventaja 1" in explanation.bullet_points
        assert "+ Ventaja 2" in explanation.bullet_points
        assert "- Riesgo 1" in explanation.bullet_points
        assert explanation.short_explanation == recommendation.summary
        assert recommendation.reasoning in explanation.full_explanation
        assert recommendation.recommendation.value in explanation.conclusion
        assert recommendation.risk_level.value in explanation.conclusion

    def test_build_explanation_handles_no_advantages_or_risks(self):
        recommendation = _recommendation(advantages=[], risks=[])
        explanation = build_explanation(recommendation)

        assert explanation.bullet_points == []
        assert "ninguno reportado" in explanation.full_explanation

    def test_rejects_empty_full_explanation(self):
        with pytest.raises(ValidationError):
            AIExplanation(full_explanation="", short_explanation="s", bullet_points=[], conclusion="c")

    def test_rejects_empty_short_explanation(self):
        with pytest.raises(ValidationError):
            AIExplanation(full_explanation="f", short_explanation="", bullet_points=[], conclusion="c")

    def test_rejects_empty_conclusion(self):
        with pytest.raises(ValidationError):
            AIExplanation(full_explanation="f", short_explanation="s", bullet_points=[], conclusion="")


# --- models.py (reexportación) ------------------------------------------------

def test_models_reexports_match_original_classes():
    assert ReexportedMarketContext is MarketContext
    assert ReexportedAIRecommendation is AIRecommendation
    assert ReexportedAIExplanation is AIExplanation
    assert ReexportedPromptVersion is PromptVersion
