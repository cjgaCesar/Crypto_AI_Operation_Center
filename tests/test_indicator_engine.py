"""
Pruebas para src/services/indicator_engine.py.

Se prueban las funciones de cálculo con series de precios donde el
resultado esperado se puede verificar a mano (ej. precios constantes, donde
SMA/EMA/Bollinger/VWAP deben dar exactamente ese mismo precio, y RSI debe
dar 50 por no haber movimiento), y con casos donde no hay suficiente
historial todavía (debe devolver None en vez de un valor inventado).
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.services.indicator_engine import (
    IndicatorEngine,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    calculate_vwap,
)
from src.models.market_data import MarketTicker
from src.utils.config import IndicatorSettings


def _history(prices, volumes=None, start=None):
    start = start or datetime(2026, 7, 19, 0, 0, 0, tzinfo=timezone.utc)
    volumes = volumes or [50.0] * len(prices)
    return [
        MarketTicker(
            exchange="Binance",
            symbol="BTCUSDT",
            price=price,
            volume_24h=volume,
            price_change_percent_24h=0.0,
            queried_at=start + timedelta(minutes=5 * i),
        )
        for i, (price, volume) in enumerate(zip(prices, volumes))
    ]


# --- SMA ---------------------------------------------------------------

def test_calculate_sma_basic():
    assert calculate_sma([1, 2, 3, 4, 5], period=3) == 4.0


def test_calculate_sma_not_enough_data_returns_none():
    assert calculate_sma([1, 2], period=3) is None


# --- EMA -----------------------------------------------------------------

def test_calculate_ema_of_constant_series_equals_the_constant():
    assert calculate_ema([50.0] * 10, period=5) == 50.0


def test_calculate_ema_not_enough_data_returns_none():
    assert calculate_ema([1.0, 2.0], period=5) is None


# --- RSI -------------------------------------------------------------------

def test_calculate_rsi_pure_uptrend_is_100():
    values = [float(v) for v in range(1, 20)]  # siempre sube
    assert calculate_rsi(values, period=14) == 100.0


def test_calculate_rsi_pure_downtrend_is_0():
    values = [float(v) for v in range(20, 1, -1)]  # siempre baja
    assert calculate_rsi(values, period=14) == 0.0


def test_calculate_rsi_flat_series_is_neutral_50():
    values = [100.0] * 20  # sin movimiento
    assert calculate_rsi(values, period=14) == 50.0


def test_calculate_rsi_not_enough_data_returns_none():
    assert calculate_rsi([1.0, 2.0], period=14) is None


# --- MACD ------------------------------------------------------------------

def test_calculate_macd_of_constant_series_is_zero():
    values = [100.0] * 10
    macd_line, macd_signal, histogram = calculate_macd(
        values, fast_period=2, slow_period=4, signal_period=2
    )
    assert macd_line == pytest.approx(0.0)
    assert macd_signal == pytest.approx(0.0)
    assert histogram == pytest.approx(0.0)


def test_calculate_macd_not_enough_data_returns_none_tuple():
    assert calculate_macd([1.0, 2.0], fast_period=12, slow_period=26, signal_period=9) == (
        None, None, None,
    )


def test_calculate_macd_enough_for_line_but_not_signal():
    # slow_period=4 -> con exactamente 4 valores hay 1 punto de macd_line,
    # pero signal_period=3 necesita al menos 3 puntos de macd_line.
    values = [100.0, 101.0, 102.0, 103.0]
    macd_line, macd_signal, histogram = calculate_macd(
        values, fast_period=2, slow_period=4, signal_period=3
    )
    assert macd_line is not None
    assert macd_signal is None
    assert histogram is None


# --- Bollinger Bands ---------------------------------------------------

def test_calculate_bollinger_bands_of_constant_series():
    upper, middle, lower = calculate_bollinger_bands([100.0] * 5, period=3, stddev_multiplier=2)
    assert upper == pytest.approx(100.0)
    assert middle == pytest.approx(100.0)
    assert lower == pytest.approx(100.0)


def test_calculate_bollinger_bands_known_values():
    upper, middle, lower = calculate_bollinger_bands([1, 2, 3], period=3, stddev_multiplier=2)
    assert middle == pytest.approx(2.0)
    assert upper == pytest.approx(3.63299, rel=1e-4)
    assert lower == pytest.approx(0.36701, rel=1e-4)


def test_calculate_bollinger_bands_not_enough_data():
    assert calculate_bollinger_bands([1.0, 2.0], period=5, stddev_multiplier=2) == (None, None, None)


# --- VWAP --------------------------------------------------------------

def test_calculate_vwap_of_constant_price_equals_the_price():
    history = _history([100.0] * 5, volumes=[10.0, 20.0, 30.0, 5.0, 8.0])
    assert calculate_vwap(history, period=5) == pytest.approx(100.0)


def test_calculate_vwap_not_enough_data_returns_none():
    history = _history([100.0, 101.0])
    assert calculate_vwap(history, period=5) is None


def test_calculate_vwap_zero_volume_returns_none():
    history = _history([100.0, 101.0, 102.0], volumes=[0.0, 0.0, 0.0])
    assert calculate_vwap(history, period=3) is None


# --- IndicatorEngine (orquestación de todos los indicadores) ---------------

def _small_settings() -> IndicatorSettings:
    return IndicatorSettings(
        sma=3, ema_fast=2, ema_medium=3, ema_slow=4, rsi=3,
        macd_fast=2, macd_slow=4, macd_signal=2,
        bollinger_period=3, bollinger_stddev=2,
        atr=14, adx=14, vwap=True,
    )


def test_engine_returns_none_with_less_than_two_readings():
    engine = IndicatorEngine(_small_settings())
    assert engine.calculate("Binance", "BTCUSDT", _history([100.0])) is None


def test_engine_calculates_all_fields_with_enough_constant_history():
    engine = IndicatorEngine(_small_settings())
    history = _history([100.0] * 10, volumes=[50.0] * 10)

    snapshot = engine.calculate("Binance", "BTCUSDT", history)

    assert snapshot is not None
    assert snapshot.exchange == "Binance"
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.sma == pytest.approx(100.0)
    assert snapshot.ema_fast == pytest.approx(100.0)
    assert snapshot.ema_medium == pytest.approx(100.0)
    assert snapshot.ema_slow == pytest.approx(100.0)
    assert snapshot.rsi == pytest.approx(50.0)
    assert snapshot.macd_line == pytest.approx(0.0)
    assert snapshot.macd_signal == pytest.approx(0.0)
    assert snapshot.macd_histogram == pytest.approx(0.0)
    assert snapshot.bollinger_upper == pytest.approx(100.0)
    assert snapshot.bollinger_middle == pytest.approx(100.0)
    assert snapshot.bollinger_lower == pytest.approx(100.0)
    assert snapshot.vwap == pytest.approx(100.0)


def test_engine_returns_partial_snapshot_with_short_history():
    """Con poca historia, los indicadores de periodo corto ya se calculan,
    pero los de periodo largo (ema_slow=4) todavía deben quedar en None."""
    engine = IndicatorEngine(_small_settings())
    history = _history([100.0, 101.0])  # solo 2 lecturas

    snapshot = engine.calculate("Binance", "BTCUSDT", history)

    assert snapshot is not None
    assert snapshot.ema_fast is not None  # ema_fast=2, alcanza
    assert snapshot.ema_slow is None       # ema_slow=4, no alcanza todavía
    assert snapshot.sma is None            # sma=3, no alcanza todavía


def test_engine_with_default_production_settings_does_not_raise():
    """Sanity check con los periodos reales de config.yaml (hasta ema_slow=200),
    para asegurar que el motor completo funciona con la configuración real."""
    settings = IndicatorSettings(
        sma=20, ema_fast=20, ema_medium=50, ema_slow=200, rsi=14,
        macd_fast=12, macd_slow=26, macd_signal=9,
        bollinger_period=20, bollinger_stddev=2,
        atr=14, adx=14, vwap=True,
    )
    engine = IndicatorEngine(settings)
    history = _history([100.0] * 250, volumes=[50.0] * 250)

    snapshot = engine.calculate("Binance", "BTCUSDT", history)

    assert snapshot is not None
    assert snapshot.ema_slow == pytest.approx(100.0)
    assert snapshot.rsi == pytest.approx(50.0)
    assert snapshot.macd_histogram == pytest.approx(0.0)


def test_engine_vwap_disabled_returns_none():
    settings = IndicatorSettings(
        sma=3, ema_fast=2, ema_medium=3, ema_slow=4, rsi=3,
        macd_fast=2, macd_slow=4, macd_signal=2,
        bollinger_period=3, bollinger_stddev=2,
        atr=14, adx=14, vwap=False,
    )
    engine = IndicatorEngine(settings)
    history = _history([100.0] * 10)

    snapshot = engine.calculate("Binance", "BTCUSDT", history)

    assert snapshot.vwap is None
