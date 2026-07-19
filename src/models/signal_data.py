"""
Modelo de datos para representar una señal de mercado generada a partir de
los indicadores técnicos ya calculados (Etapa 2).

Esta etapa (3) NO usa inteligencia artificial: 'SignalSnapshot' es el
resultado de combinar reglas determinísticas y configurables
(src/signals/rules/) sobre valores ya calculados de EMA, RSI, MACD y
Bollinger. Está pensado para que la IA, el dashboard y el motor de trading
de etapas futuras lo consuman directamente, sin tener que recalcular nada.

Guarda el resultado final (trend, ema_signal, macd_signal, rsi_signal,
bollinger_signal, score, confidence, signal_type), la fuerza individual de
cada regla (*_rule_strength, 0.0 a 1.0) y el detalle completo de CADA regla
(su 'reason', el porqué de su resultado), para que una futura IA pueda
explicar una señal sin recalcular ningún indicador ni volver a ejecutar
ninguna regla.

Los campos de categoría (trend, ema_signal, macd_signal, rsi_signal,
bollinger_signal, confidence, signal_type) usan directamente los Enums del
motor de señales (no 'str' sueltos): Pydantic los valida al construir el
modelo, y SQLiteSignalRepository los serializa explícitamente a texto
(.value) al guardarlos, reconstruyéndolos como Enum al leerlos de vuelta.

Ejemplo completo:

    SignalSnapshot(
        exchange="Binance", symbol="BTCUSDT",
        trend=TrendLabel.STRONG_BULLISH, trend_strength=TrendStrength.STRONG,
        ema_signal=EMALabel.BULLISH, macd_signal=MACDLabel.BULLISH_CROSS,
        rsi_signal=RSILabel.OVERBOUGHT, bollinger_signal=BollingerLabel.UPPER_BAND,
        trend_reason="EMA rápida +10.00% sobre la EMA lenta, con las 3 EMA alineadas al alza.",
        ema_reason="EMA rápida está +4.76% sobre la EMA media.",
        macd_reason="MACD (1.5000) por encima de su línea de señal (1.0000).",
        rsi_reason="RSI en 75.00, por encima del umbral de sobrecompra (70).",
        bollinger_reason="Precio (109.0000) cerca o sobre la banda superior (110.0000).",
        trend_rule_strength=1.0, ema_rule_strength=1.0, macd_rule_strength=0.2,
        rsi_rule_strength=0.1667, bollinger_rule_strength=0.5,
        score=83.25, confidence=ConfidenceLevel.VERY_HIGH, signal_type=SignalType.BULLISH,
        generated_at=datetime.now(timezone.utc),
    )
"""

from datetime import datetime

from pydantic import BaseModel, Field

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


class SignalSnapshot(BaseModel):
    """Señal estructurada calculada para (exchange, symbol) en un instante."""

    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)

    trend: TrendLabel
    trend_strength: TrendStrength
    ema_signal: EMALabel
    macd_signal: MACDLabel
    rsi_signal: RSILabel
    bollinger_signal: BollingerLabel

    # Explicación en texto de cada regla (RuleResult.reason), para que una
    # futura IA pueda responder "¿por qué apareció esta señal?" sin
    # recalcular nada. No se exige que sean no vacíos a nivel de modelo
    # (a propósito): los registros migrados desde el esquema anterior de
    # market_signals (antes de esta ampliación) se leen con reason='' como
    # valor por defecto, y el modelo debe poder reconstruirlos igual. Las
    # 5 reglas actuales SIEMPRE producen un reason no vacío para señales
    # nuevas (ver tests/test_signals_*_rule.py), así que en la práctica
    # nunca están vacíos salvo en datos históricos migrados.
    trend_reason: str
    ema_reason: str
    macd_reason: str
    rsi_reason: str
    bollinger_reason: str

    # Fuerza individual de cada regla (RuleResult.strength), 0.0 a 1.0.
    trend_rule_strength: float = Field(ge=0.0, le=1.0)
    ema_rule_strength: float = Field(ge=0.0, le=1.0)
    macd_rule_strength: float = Field(ge=0.0, le=1.0)
    rsi_rule_strength: float = Field(ge=0.0, le=1.0)
    bollinger_rule_strength: float = Field(ge=0.0, le=1.0)

    score: float = Field(ge=0.0, le=100.0)
    confidence: ConfidenceLevel
    signal_type: SignalType

    generated_at: datetime
