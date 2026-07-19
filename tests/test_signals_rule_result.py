"""
Pruebas para el modelo RuleResult (src/signals/rule_result.py) y los enums
comunes del motor de señales (src/signals/enums.py), incluyendo los enums
de "label" específicos de cada regla.
"""

import pytest
from pydantic import ValidationError

from src.signals.enums import (
    BollingerLabel,
    ConfidenceLevel,
    Direction,
    EMALabel,
    MACDLabel,
    RSILabel,
    SignalType,
    TrendLabel,
    TrendStrength,
)
from src.signals.rule_result import RuleResult


def test_rule_result_holds_direction_strength_reason_and_label():
    result = RuleResult[TrendLabel](
        direction=Direction.BULLISH,
        strength=0.82,
        reason="EMA20 está sobre EMA50",
        label=TrendLabel.BULLISH,
    )
    assert result.direction == Direction.BULLISH
    assert result.strength == 0.82
    assert result.reason == "EMA20 está sobre EMA50"
    assert result.label == TrendLabel.BULLISH
    assert isinstance(result.label, TrendLabel)


def test_rule_result_accepts_direction_as_plain_string_value():
    """Direction es un str Enum: aceptar el valor de texto directamente
    facilita construir RuleResult desde datos ya serializados (ej. JSON)."""
    result = RuleResult[TrendLabel](
        direction="Bearish", strength=0.5, reason="r", label=TrendLabel.BEARISH
    )
    assert result.direction == Direction.BEARISH


def test_rule_result_rejects_invalid_direction():
    with pytest.raises(ValidationError):
        RuleResult[TrendLabel](
            direction="Sideways", strength=0.5, reason="r", label=TrendLabel.NEUTRAL
        )


def test_rule_result_requires_all_fields():
    with pytest.raises(ValidationError):
        RuleResult[TrendLabel](direction=Direction.NEUTRAL)


def test_rule_result_rejects_non_numeric_strength():
    with pytest.raises(ValidationError):
        RuleResult[TrendLabel](
            direction=Direction.NEUTRAL, strength="fuerte", reason="r", label=TrendLabel.NEUTRAL
        )


# --- Validación del rango de 'strength' (0.0 a 1.0) ------------------------

@pytest.mark.parametrize("strength", [0.0, 0.5, 1.0])
def test_rule_result_accepts_strength_within_valid_range(strength):
    result = RuleResult[TrendLabel](
        direction=Direction.NEUTRAL, strength=strength, reason="r", label=TrendLabel.NEUTRAL
    )
    assert result.strength == strength


@pytest.mark.parametrize("strength", [-0.01, -1.0, 1.01, 2.0, 100.0])
def test_rule_result_rejects_strength_outside_valid_range(strength):
    with pytest.raises(ValidationError):
        RuleResult[TrendLabel](
            direction=Direction.NEUTRAL, strength=strength, reason="r", label=TrendLabel.NEUTRAL
        )


# --- RuleResult genérico: cada regla valida contra SU propio enum de label -

def test_rule_result_rejects_label_value_not_in_the_parameterized_enum():
    """RSILabel.OVERSOLD ('Oversold') no existe como valor en BollingerLabel:
    debe rechazarse al parametrizar RuleResult[BollingerLabel]."""
    with pytest.raises(ValidationError):
        RuleResult[BollingerLabel](
            direction=Direction.BEARISH, strength=0.5, reason="r", label=RSILabel.OVERSOLD
        )


def test_rule_result_normalizes_shared_value_to_the_parameterized_enum_type():
    """TrendLabel y EMALabel comparten el valor de texto 'Bullish'. Al
    parametrizar RuleResult[TrendLabel], el resultado SIEMPRE queda tipado
    como TrendLabel (nunca como EMALabel), sin importar qué objeto se haya
    pasado, porque Pydantic normaliza el valor al tipo exacto solicitado."""
    result = RuleResult[TrendLabel](
        direction=Direction.BULLISH, strength=0.5, reason="r", label=EMALabel.BULLISH
    )
    assert isinstance(result.label, TrendLabel)
    assert not isinstance(result.label, EMALabel)
    assert result.label == TrendLabel.BULLISH


# --- Enums comunes ----------------------------------------------------

def test_direction_has_exactly_three_values():
    assert {d.value for d in Direction} == {"Bullish", "Neutral", "Bearish"}


def test_trend_strength_has_exactly_three_values():
    assert {t.value for t in TrendStrength} == {"Weak", "Medium", "Strong"}


def test_confidence_level_has_exactly_five_values():
    assert {c.value for c in ConfidenceLevel} == {
        "Very Low", "Low", "Medium", "High", "Very High",
    }


def test_signal_type_has_exactly_three_values():
    assert {s.value for s in SignalType} == {"Bullish", "Neutral", "Bearish"}


def test_direction_and_signal_type_are_distinct_enums():
    """Aunque comparten los mismos 3 valores de texto (por lo que
    Direction.BULLISH == SignalType.BULLISH, propio de los str Enum),
    Direction (por regla) y SignalType (veredicto general) son clases de
    enum distintas, a propósito, según lo pedido explícitamente."""
    assert Direction is not SignalType
    assert not isinstance(SignalType.BULLISH, Direction)
    assert Direction.BULLISH.value == SignalType.BULLISH.value


# --- Enums de labels específicos de cada regla -----------------------------

def test_trend_label_has_exactly_five_values():
    assert {t.value for t in TrendLabel} == {
        "Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish",
    }


def test_ema_label_has_exactly_three_values():
    assert {e.value for e in EMALabel} == {"Bullish", "Neutral", "Bearish"}


def test_macd_label_has_exactly_three_values():
    assert {m.value for m in MACDLabel} == {"Bullish Cross", "Neutral", "Bearish Cross"}


def test_rsi_label_has_exactly_three_values():
    assert {r.value for r in RSILabel} == {"Oversold", "Neutral", "Overbought"}


def test_bollinger_label_has_exactly_three_values():
    assert {b.value for b in BollingerLabel} == {"Upper Band", "Inside Bands", "Lower Band"}


def test_label_enums_are_all_distinct_classes():
    label_enums = [TrendLabel, EMALabel, MACDLabel, RSILabel, BollingerLabel]
    assert len(set(label_enums)) == 5
