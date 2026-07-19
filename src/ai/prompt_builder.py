"""
Constructor del prompt que se envía al proveedor de IA (Etapa 4).

Convierte un MarketContext en texto plano, exponiendo toda la información
relevante (señal, indicadores, precio, razones, strength, confidence,
trend, signal_type) para que el proveedor razone sobre ella. El prompt NO
contiene lógica de negocio: solo expone información ya calculada por las
Etapas 2 y 3, en el mismo orden y con las mismas etiquetas siempre, para
que sea determinista y fácil de auditar.
"""

from enum import Enum

from src.ai.context import MarketContext
from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot


class PromptVersion(str, Enum):
    """Versión del formato de prompt que PromptBuilder genera.

    Tipada (en vez de un string suelto) para que 'prompt_version' en
    AIRecommendation no acepte cualquier texto arbitrario: solo una versión
    de prompt real y conocida. Si el formato del prompt cambia de forma que
    afecte cómo un proveedor debe interpretarlo, agregar un nuevo miembro
    aquí (ej. V2 = "v2") en vez de reemplazar V1, para poder seguir
    reconstruyendo AIRecommendation ya guardadas con la versión anterior.
    """

    V1 = "v1"


# Versión de prompt que PromptBuilder produce hoy. DecisionEngine la usa
# para completar 'AIRecommendation.prompt_version' en cada recomendación
# nueva, sin que el proveedor de IA necesite saber nada de esto.
CURRENT_PROMPT_VERSION = PromptVersion.V1


class PromptBuilder:
    def build(self, context: MarketContext, system_prompt: str) -> str:
        sections = [system_prompt.strip(), "", self._market_section(context)]

        if context.indicators is not None:
            sections += ["", self._indicators_section(context.indicators)]

        if context.latest_signal is not None:
            sections += ["", self._signal_section(context.latest_signal)]

        if context.recent_signals:
            sections += ["", self._history_section(context.recent_signals)]

        return "\n".join(sections)

    @staticmethod
    def _market_section(context: MarketContext) -> str:
        return (
            f"Exchange: {context.exchange}\n"
            f"Symbol: {context.symbol}\n"
            f"Current Price: {context.current_price}"
        )

    @staticmethod
    def _indicators_section(indicators: IndicatorSnapshot) -> str:
        return (
            "Indicators:\n"
            f"- SMA: {indicators.sma}\n"
            f"- EMA fast/medium/slow: {indicators.ema_fast} / {indicators.ema_medium} / {indicators.ema_slow}\n"
            f"- RSI: {indicators.rsi}\n"
            f"- MACD line/signal/histogram: {indicators.macd_line} / {indicators.macd_signal} / {indicators.macd_histogram}\n"
            f"- Bollinger upper/middle/lower: {indicators.bollinger_upper} / {indicators.bollinger_middle} / {indicators.bollinger_lower}\n"
            f"- VWAP: {indicators.vwap}"
        )

    @staticmethod
    def _signal_section(signal: SignalSnapshot) -> str:
        return (
            "Latest Signal:\n"
            f"- Trend: {signal.trend.value} "
            f"(trend_strength: {signal.trend_strength.value}, rule_strength: {signal.trend_rule_strength:.2f}) "
            f"- {signal.trend_reason}\n"
            f"- EMA: {signal.ema_signal.value} (rule_strength: {signal.ema_rule_strength:.2f}) - {signal.ema_reason}\n"
            f"- MACD: {signal.macd_signal.value} (rule_strength: {signal.macd_rule_strength:.2f}) - {signal.macd_reason}\n"
            f"- RSI: {signal.rsi_signal.value} (rule_strength: {signal.rsi_rule_strength:.2f}) - {signal.rsi_reason}\n"
            f"- Bollinger: {signal.bollinger_signal.value} (rule_strength: {signal.bollinger_rule_strength:.2f}) - {signal.bollinger_reason}\n"
            f"- Score: {signal.score:.2f}\n"
            f"- Confidence: {signal.confidence.value}\n"
            f"- Signal Type: {signal.signal_type.value}"
        )

    @staticmethod
    def _history_section(recent_signals: list[SignalSnapshot]) -> str:
        lines = [
            f"- {s.generated_at.isoformat()}: signal_type={s.signal_type.value}, score={s.score:.2f}"
            for s in recent_signals
        ]
        return "Recent Signal History (oldest to newest):\n" + "\n".join(lines)
