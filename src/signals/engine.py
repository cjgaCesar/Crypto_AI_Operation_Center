"""
Motor de señales: lógica de negocio pura (sin I/O), igual en espíritu a
IndicatorEngine (src/services/indicator_engine.py).

Recibe un IndicatorSnapshot ya calculado (Etapa 2) y el precio actual, y
devuelve un SignalSnapshot. No sabe leer de SQLite ni de ningún
repositorio: eso es responsabilidad de SignalService.

No usa inteligencia artificial: ejecuta las 5 reglas determinísticas de
src/signals/rules/ (cada una devuelve un RuleResult tipado, nunca un
string suelto) y combina sus resultados con el agregador
(src/signals/aggregator.py). Conserva el 'label', 'reason' y 'strength' de
cada regla en el SignalSnapshot final, para que una futura IA pueda
explicar la señal sin recalcular nada.
"""

from datetime import datetime, timezone
from typing import Optional

from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot
from src.signals.aggregator import aggregate
from src.signals.rules.bollinger_rule import BollingerRule
from src.signals.rules.ema_rule import EMARule
from src.signals.rules.macd_rule import MACDRule
from src.signals.rules.rsi_rule import RSIRule
from src.signals.rules.trend_rule import TrendRule
from src.utils.config import SignalSettings


class SignalEngine:
    def __init__(self, settings: SignalSettings):
        self.settings = settings
        self._trend_rule = TrendRule(settings.rules.trend)
        self._ema_rule = EMARule(settings.rules.ema)
        self._macd_rule = MACDRule()
        self._rsi_rule = RSIRule(settings.rules.rsi)
        self._bollinger_rule = BollingerRule(settings.rules.bollinger)

    def calculate(
        self,
        exchange: str,
        symbol: str,
        indicators: Optional[IndicatorSnapshot],
        price: Optional[float],
    ) -> Optional[SignalSnapshot]:
        """Ejecuta las 5 reglas sobre 'indicators' y 'price', y combina el
        resultado en un SignalSnapshot.

        Devuelve None si no hay indicadores o precio disponibles todavía
        (ej. IndicatorService aún no generó ningún snapshot para este
        símbolo). Los campos individuales de 'indicators' sí pueden ser
        None (indicador todavía sin suficiente historial): cada regla
        maneja eso internamente devolviendo un RuleResult neutral.
        """
        if indicators is None or price is None:
            return None

        trend = self._trend_rule.evaluate(
            indicators.ema_fast, indicators.ema_medium, indicators.ema_slow
        )
        ema = self._ema_rule.evaluate(indicators.ema_fast, indicators.ema_medium)
        macd = self._macd_rule.evaluate(indicators.macd_line, indicators.macd_signal)
        rsi = self._rsi_rule.evaluate(indicators.rsi)
        bollinger = self._bollinger_rule.evaluate(
            price, indicators.bollinger_upper, indicators.bollinger_lower
        )

        aggregated = aggregate(
            trend=trend,
            ema=ema,
            macd=macd,
            rsi=rsi,
            bollinger=bollinger,
            weights=self.settings.weights,
            score_thresholds=self.settings.score,
            confidence_thresholds=self.settings.confidence,
        )

        return SignalSnapshot(
            exchange=exchange,
            symbol=symbol,
            trend=trend.label,
            trend_strength=aggregated.trend_strength,
            ema_signal=ema.label,
            macd_signal=macd.label,
            rsi_signal=rsi.label,
            bollinger_signal=bollinger.label,
            trend_reason=trend.reason,
            ema_reason=ema.reason,
            macd_reason=macd.reason,
            rsi_reason=rsi.reason,
            bollinger_reason=bollinger.reason,
            trend_rule_strength=trend.strength,
            ema_rule_strength=ema.strength,
            macd_rule_strength=macd.strength,
            rsi_rule_strength=rsi.strength,
            bollinger_rule_strength=bollinger.strength,
            score=aggregated.score,
            confidence=aggregated.confidence,
            signal_type=aggregated.signal_type,
            generated_at=datetime.now(timezone.utc),
        )
