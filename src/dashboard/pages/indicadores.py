"""
Página 'Indicadores' (Etapa 5, Iteración 5.5 — funcional y responsive).

Muestra, para el símbolo elegido en la barra lateral (selector compartido
en app.py), el último valor de cada indicador técnico calculado
(RSI, MACD/Señal/Histograma, SMA, EMA rápida/media/lenta, Bandas de
Bollinger, VWAP), la fecha del último cálculo y el historial de esos
indicadores en 3 gráficos de línea.

Todo lo que se muestra viene de service.get_indicators_page(): esta
página no llama al repositorio, no ejecuta SQL, no importa sqlite3 y no
recalcula ningún indicador. Solo se muestran indicadores que realmente
existen en 'market_indicators': un valor ausente (todavía no calculado)
se muestra como "N/D", nunca inventado. ATR, ADX y Volatilidad no
existen en este proyecto todavía (ver README) y se declaran
explícitamente como no disponibles, en vez de omitirse en silencio.

El selector "Vista" (Automática/Amplia/Compacta) se obtiene llamando a
layout.render_view_mode_selector() — la misma función que usan 'Resumen
General' y 'Mercado', no una construcción propia.
"""

import streamlit as st

from src.dashboard.components import (
    render_indicator_availability,
    render_indicator_history_charts,
    render_indicator_metrics,
    render_not_available,
)
from src.dashboard.layout import is_compact, render_view_mode_selector
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title("Indicadores")
    st.caption(f"Indicadores técnicos calculados para {symbol}.")

    view_mode = render_view_mode_selector()
    compact = is_compact(view_mode)

    page = service.get_indicators_page(exchange, symbol, limit=limit)

    if not page.data_available or page.summary is None:
        render_not_available(page.message or f"Todavía no hay indicadores calculados para {symbol}.")
        return

    render_indicator_metrics(page.summary, compact=compact)
    st.divider()
    render_indicator_history_charts(page.history, symbol=page.selected_symbol)
    st.divider()
    render_indicator_availability(page.summary)
