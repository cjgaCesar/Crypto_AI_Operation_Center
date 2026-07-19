"""
Página 'Indicadores' (Etapa 5, Iteración 5.2 — esqueleto).

La Iteración 5.3 mostrará gráficos de RSI, MACD y Bandas de Bollinger.
Por ahora solo confirma que el último snapshot de indicadores se puede leer.
"""

import streamlit as st

from src.dashboard.components import render_not_available
from src.dashboard.formatters import format_price, format_timestamp
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title(f"Indicadores — {symbol}")
    st.caption("Estructura base (Iteración 5.2) — sin gráficos completos todavía.")

    history = service.get_indicators_view(exchange, symbol, limit=1)
    indicators = history[-1] if history else None

    if indicators is None:
        render_not_available(f"Todavía no hay indicadores calculados para {symbol}.")
        return

    st.write(f"RSI: {format_price(indicators.rsi, decimals=2)}")
    st.write(f"Calculado: {format_timestamp(indicators.calculated_at)}")
