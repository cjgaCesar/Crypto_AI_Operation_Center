"""
Página 'Señales' (Etapa 5, Iteración 5.6 — funcional y responsive).

Muestra, para el símbolo elegido en la barra lateral (selector compartido
en app.py), la última señal generada (tipo, score, confianza, tendencia y
su fuerza, y el veredicto de cada componente: EMA/MACD/RSI/Bollinger), la
fecha de generación, la cantidad de registros disponibles, un gráfico con
la evolución del score y una tabla cronológica de señal/confianza/
tendencia.

Todo lo que se muestra viene de service.get_signals_page(): esta página
no llama al repositorio, no ejecuta SQL, no importa sqlite3 y no
recalcula ni regenera ninguna señal (no llama a SignalEngine). El riesgo
no aparece aquí: no es un campo de 'market_signals' (vive en
'ai_recommendations', página 'Recomendaciones de IA', todavía no
implementada).

El selector "Vista" (Automática/Amplia/Compacta) se obtiene llamando a
layout.render_view_mode_selector() — la misma función que usan 'Resumen
General', 'Mercado' e 'Indicadores', no una construcción propia.
"""

import streamlit as st

from src.dashboard.components import (
    render_not_available,
    render_signal_availability,
    render_signal_explanation,
    render_signal_history_chart,
    render_signal_history_table,
    render_signal_metrics,
    render_signal_status,
)
from src.dashboard.layout import is_compact, render_view_mode_selector
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title("Señales")
    st.caption(f"Última señal generada y su historial para {symbol}.")

    view_mode = render_view_mode_selector()
    compact = is_compact(view_mode)

    page = service.get_signals_page(exchange, symbol, limit=limit)

    if not page.data_available or page.summary is None:
        render_not_available(page.message or f"Todavía no hay señales generadas para {symbol}.")
        return

    render_signal_status(page.summary)
    render_signal_metrics(page.summary, compact=compact)
    st.divider()
    render_signal_explanation(page.summary, compact=compact)
    st.divider()
    render_signal_history_chart(page.history, symbol=page.selected_symbol)
    render_signal_history_table(page.history)
    st.divider()
    render_signal_availability(page.summary)
