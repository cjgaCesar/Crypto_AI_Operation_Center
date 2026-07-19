"""
Motor de cálculo de indicadores técnicos.

Es lógica de negocio pura: recibe el historial de precios de un símbolo
(lista de MarketTicker, ordenada del más antiguo al más reciente) y la
configuración de periodos (IndicatorSettings), y devuelve un
IndicatorSnapshot. No sabe nada de Binance, ni de SQLite, ni de otros
exchanges — por eso se puede probar con listas de precios de prueba, sin
red ni base de datos.

Cada indicador requiere una cantidad mínima de lecturas para poder
calcularse (ej. la EMA lenta necesita al menos 'ema_slow' lecturas). Si no
hay suficiente historial todavía, ese campo queda en None en vez de
inventar un valor: es lo esperado mientras el proyecto recién empieza a
acumular datos.

Limitación conocida (documentada también en config.yaml y ARQUITECTURA.md):
ATR y ADX NO se calculan en esta etapa. Ambos requieren datos de máximo y
mínimo por vela (OHLC), que Binance expone en el endpoint de velas
(/api/v3/klines), no en el endpoint de ticker de 24h que usa este proyecto
(src/market/binance.py). Calcularlos aproximadamente solo con el precio de
cierre produciría un número que no sería un ATR/ADX real, lo cual sería
riesgoso si una etapa futura (señales, trading) confiara en él. Sus
periodos ya están reservados en la configuración para cuando se incorpore
esa fuente de datos.
"""

from datetime import datetime, timezone
from typing import Optional

from src.models.indicator_data import IndicatorSnapshot
from src.models.market_data import MarketTicker
from src.utils.config import IndicatorSettings


def calculate_sma(values: list[float], period: int) -> Optional[float]:
    """Media móvil simple de las últimas 'period' lecturas."""
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _ema_series(values: list[float], period: int) -> list[float]:
    """Serie completa de EMA (semillada con la SMA de las primeras 'period'
    lecturas). Lista vacía si no hay suficientes datos."""
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)
    ema_values = [sum(values[:period]) / period]  # semilla: SMA inicial
    for price in values[period:]:
        ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def calculate_ema(values: list[float], period: int) -> Optional[float]:
    """Último valor de la media móvil exponencial de 'period' lecturas."""
    series = _ema_series(values, period)
    return series[-1] if series else None


def calculate_rsi(values: list[float], period: int) -> Optional[float]:
    """RSI (índice de fuerza relativa) con suavizado de Wilder."""
    if len(values) < period + 1:
        return None

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # Sin movimiento de precio: RSI neutral.
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(
    values: list[float], fast_period: int, slow_period: int, signal_period: int
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Devuelve (macd_line, signal_line, histogram). Cualquiera puede ser
    None si todavía no hay suficiente historial para calcularlo."""
    fast_series = _ema_series(values, fast_period)
    slow_series = _ema_series(values, slow_period)

    if not slow_series:
        return None, None, None

    # slow_series siempre arranca más tarde que fast_series (necesita más
    # historial); se recorta fast_series para que ambas queden alineadas al
    # mismo instante de tiempo.
    offset = slow_period - fast_period
    fast_aligned = fast_series[offset:]
    macd_series = [f - s for f, s in zip(fast_aligned, slow_series)]

    macd_line = macd_series[-1]

    signal_series = _ema_series(macd_series, signal_period)
    if not signal_series:
        return macd_line, None, None

    signal_line = signal_series[-1]
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    values: list[float], period: int, stddev_multiplier: float
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Devuelve (upper, middle, lower). None, None, None si falta historial."""
    if len(values) < period:
        return None, None, None

    window = values[-period:]
    middle = sum(window) / period
    variance = sum((v - middle) ** 2 for v in window) / period
    std = variance ** 0.5

    upper = middle + stddev_multiplier * std
    lower = middle - stddev_multiplier * std
    return upper, middle, lower


def calculate_vwap(history: list[MarketTicker], period: int) -> Optional[float]:
    """Precio promedio ponderado por volumen de las últimas 'period' lecturas.

    Aproximación: usa 'volume_24h' (volumen acumulado de 24h que reporta
    Binance) como peso de cada lectura, ya que este proyecto no consulta
    todavía el volumen negociado por intervalo (requeriría el endpoint de
    velas). Sirve como referencia de precio ponderado, no como el VWAP
    exacto de un exchange.
    """
    if len(history) < period:
        return None

    window = history[-period:]
    total_volume = sum(t.volume_24h for t in window)
    if total_volume == 0:
        return None

    weighted_sum = sum(t.price * t.volume_24h for t in window)
    return weighted_sum / total_volume


class IndicatorEngine:
    def __init__(self, settings: IndicatorSettings):
        self.settings = settings

    def calculate(
        self, exchange: str, symbol: str, history: list[MarketTicker]
    ) -> Optional[IndicatorSnapshot]:
        """Calcula los indicadores disponibles a partir del historial dado.

        Devuelve None únicamente si no hay ni siquiera 2 lecturas (no se
        puede calcular absolutamente nada). Con menos historial del
        necesario para un indicador puntual, ese campo queda en None pero
        el resto de los indicadores que sí tengan suficientes datos se
        calculan igual.
        """
        if len(history) < 2:
            return None

        closes = [t.price for t in history]
        settings = self.settings

        sma = calculate_sma(closes, settings.sma)
        ema_fast = calculate_ema(closes, settings.ema_fast)
        ema_medium = calculate_ema(closes, settings.ema_medium)
        ema_slow = calculate_ema(closes, settings.ema_slow)
        rsi = calculate_rsi(closes, settings.rsi)
        macd_line, macd_signal, macd_histogram = calculate_macd(
            closes, settings.macd_fast, settings.macd_slow, settings.macd_signal
        )
        bollinger_upper, bollinger_middle, bollinger_lower = calculate_bollinger_bands(
            closes, settings.bollinger_period, settings.bollinger_stddev
        )
        vwap = calculate_vwap(history, settings.sma) if settings.vwap else None

        return IndicatorSnapshot(
            exchange=exchange,
            symbol=symbol,
            sma=sma,
            ema_fast=ema_fast,
            ema_medium=ema_medium,
            ema_slow=ema_slow,
            rsi=rsi,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            bollinger_upper=bollinger_upper,
            bollinger_middle=bollinger_middle,
            bollinger_lower=bollinger_lower,
            vwap=vwap,
            calculated_at=datetime.now(timezone.utc),
        )
