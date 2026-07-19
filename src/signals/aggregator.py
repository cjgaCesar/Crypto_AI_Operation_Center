"""
Agregador de señales.

Combina los RuleResult de las 5 reglas (src/signals/rules/) en una
evaluación global. Es el único lugar del proyecto que sabe cómo combinar
reglas individuales en un resultado conjunto; las reglas mismas no se
conocen entre sí (Single Responsibility).

====================================================================
CUATRO CONCEPTOS DISTINTOS QUE NO DEBEN CONFUNDIRSE
====================================================================

- **strength** (por regla, en RuleResult): qué tan fuerte es la señal de
  ESA regla en particular, de 0.0 a 1.0, según sus propios umbrales (ej.
  qué tan lejos está el RSI de su umbral de sobrecompra). Es información
  LOCAL a una sola regla; no sabe nada de las otras 4.

- **score** (por señal agregada, 0-100): combina dirección × strength de
  las 5 reglas, PONDERADO por el peso configurado de cada una
  (signals.weights). Responde "¿qué tan alcista o bajista es la señal en
  conjunto, y con qué convicción?". Una sola regla con mucho peso y mucha
  fuerza puede dominar el score, aunque las demás no coincidan.

- **confidence** (por señal agregada): mide el ACUERDO entre las 5
  reglas en su 'direction' (alcista/neutral/bajista), SIN IMPORTAR los
  pesos ni la fuerza de cada una. Responde "¿qué tan de acuerdo están las
  reglas entre sí?". Se puede tener un score alto con confidence bajo (ej.
  una sola regla con peso enorme y fuerza máxima, mientras las otras 4
  apuntan en sentido contrario: el score refleja la regla dominante, pero
  la confianza es baja porque no hay consenso).

- **trend_strength** (por señal agregada): NO es un resumen de las 5
  reglas ni de 'strength' en general. Se deriva ÚNICAMENTE del resultado
  de TrendRule (su 'label'): Strong Bullish/Strong Bearish -> Strong;
  Bullish/Bearish -> Medium; Neutral -> Weak. Es una clasificación
  cualitativa de la tendencia principal, no una fuerza combinada.

====================================================================
CÓMO SE CALCULA CADA CAMPO
====================================================================

- score: ver arriba. `score = 50 + (Σ peso_i × signo(dirección_i) ×
  strength_i / Σ peso_i) × 50`. Rango resultante: 0-100.
- confidence: se cuenta cuántas de las 5 reglas comparten la dirección más
  frecuente (sin ponderar por peso), se expresa como % (0-100), y se
  clasifica según signals.confidence. Ver la sección "EMPATES" más abajo
  para el comportamiento exacto cuando hay dos o más direcciones con la
  misma cantidad de reglas.
- trend_strength: ver arriba.
- signal_type: clasifica el 'score' final (ya ponderado) en Bullish/
  Neutral/Bearish, usando signals.score (bullish/bearish como límites;
  neutral es solo referencia informativa). Es el veredicto general, no el
  de una regla individual (eso es 'direction').

====================================================================
EMPATES EN CONFIDENCE: COMPORTAMIENTO EXPLÍCITO
====================================================================

confidence NO necesita saber CUÁL dirección es mayoritaria, solo CUÁNTAS
reglas comparten la dirección más frecuente. Por eso, un empate entre dos o
tres inclinaciones (ej. 2 reglas alcistas y 2 bajistas, con 1 neutral) no
es ambiguo: el tamaño del grupo más grande es igualmente 2, sin importar
cuál de los dos grupos empatados se mire primero.

La implementación calcula explícitamente `directions.count(BULLISH)`,
`directions.count(NEUTRAL)` y `directions.count(BEARISH)` por separado, y
usa `max()` sobre esos 3 números. Esto es determinístico por construcción:
no depende del orden de un diccionario, de un Counter, ni del orden en que
llegan las reglas. (La versión anterior usaba
`Counter(directions).most_common(1)[0][1]`: el valor numérico ya era
correcto — most_common() siempre devuelve el conteo máximo real,
independientemente del desempate interno — pero se reemplazó de todas
formas por claridad: así cualquiera que lea el código puede verificar en
una línea que el resultado es determinístico, sin tener que conocer las
reglas de desempate internas de Counter.most_common().)
"""

from dataclasses import dataclass

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
from src.utils.config import ConfidenceThresholds, ScoreThresholds, SignalWeights

_DIRECTION_SIGN = {
    Direction.BULLISH: 1,
    Direction.NEUTRAL: 0,
    Direction.BEARISH: -1,
}

_STRONG_TREND_LABELS = (TrendLabel.STRONG_BULLISH, TrendLabel.STRONG_BEARISH)


@dataclass(frozen=True)
class AggregatedSignal:
    score: float
    confidence: ConfidenceLevel
    trend_strength: TrendStrength
    signal_type: SignalType


def _classify_confidence(
    confidence_score: float, thresholds: ConfidenceThresholds
) -> ConfidenceLevel:
    if confidence_score >= thresholds.very_high:
        return ConfidenceLevel.VERY_HIGH
    if confidence_score >= thresholds.high:
        return ConfidenceLevel.HIGH
    if confidence_score >= thresholds.medium:
        return ConfidenceLevel.MEDIUM
    if confidence_score >= thresholds.low:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.VERY_LOW


def _classify_signal_type(score: float, thresholds: ScoreThresholds) -> SignalType:
    if score >= thresholds.bullish:
        return SignalType.BULLISH
    if score <= thresholds.bearish:
        return SignalType.BEARISH
    return SignalType.NEUTRAL


def _trend_strength_from_result(trend: RuleResult[TrendLabel]) -> TrendStrength:
    if trend.direction == Direction.NEUTRAL:
        return TrendStrength.WEAK
    if trend.label in _STRONG_TREND_LABELS:
        return TrendStrength.STRONG
    return TrendStrength.MEDIUM


def _majority_share(directions: list[Direction]) -> float:
    """Proporción (0.0 a 1.0) de reglas que comparten la dirección más
    frecuente. Determinístico: compara los 3 conteos explícitos con max(),
    sin depender de Counter ni de ningún orden de iteración. En caso de
    empate entre dos o tres direcciones, el resultado es el mismo (el
    tamaño del grupo empatado), porque no importa CUÁL dirección empata,
    solo CUÁNTAS reglas están de acuerdo con la más numerosa.
    """
    bullish_count = directions.count(Direction.BULLISH)
    neutral_count = directions.count(Direction.NEUTRAL)
    bearish_count = directions.count(Direction.BEARISH)
    majority_count = max(bullish_count, neutral_count, bearish_count)
    return majority_count / len(directions)


def aggregate(
    trend: RuleResult[TrendLabel],
    ema: RuleResult[EMALabel],
    macd: RuleResult[MACDLabel],
    rsi: RuleResult[RSILabel],
    bollinger: RuleResult[BollingerLabel],
    weights: SignalWeights,
    score_thresholds: ScoreThresholds,
    confidence_thresholds: ConfidenceThresholds,
) -> AggregatedSignal:
    results = {
        "trend": trend,
        "ema": ema,
        "macd": macd,
        "rsi": rsi,
        "bollinger": bollinger,
    }
    weight_by_rule = {
        "trend": weights.trend,
        "ema": weights.ema,
        "macd": weights.macd,
        "rsi": weights.rsi,
        "bollinger": weights.bollinger,
    }

    total_weight = sum(weight_by_rule.values())
    weighted_sum = sum(
        weight_by_rule[name] * _DIRECTION_SIGN[result.direction] * result.strength
        for name, result in results.items()
    )
    normalized = (weighted_sum / total_weight) if total_weight else 0.0  # rango [-1, 1]
    score = 50 + normalized * 50  # rango [0, 100]
    score = max(0.0, min(100.0, score))

    directions = [result.direction for result in results.values()]
    confidence_score = _majority_share(directions) * 100
    confidence = _classify_confidence(confidence_score, confidence_thresholds)

    trend_strength = _trend_strength_from_result(trend)
    signal_type = _classify_signal_type(score, score_thresholds)

    return AggregatedSignal(
        score=score,
        confidence=confidence,
        trend_strength=trend_strength,
        signal_type=signal_type,
    )
