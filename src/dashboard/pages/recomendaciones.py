"""
Página 'Recomendaciones de IA' (Etapa 5, Iteración 5.7 — funcional y
responsive).

Muestra, para el símbolo elegido en la barra lateral (selector compartido
en app.py), la última recomendación de IA (acción sugerida, confianza,
nivel de riesgo, resumen y razonamiento completo con ventajas/riesgos),
la fecha de generación, la cantidad de registros disponibles, un gráfico
con la evolución de la confianza y una tabla cronológica de
recomendación/confianza/riesgo.

Todo lo que se muestra viene de service.get_ai_recommendations_page():
esta página no llama al repositorio, no ejecuta SQL, no importa sqlite3
y no recalcula ni regenera ninguna recomendación (no llama a
DecisionEngine ni a ningún AIProvider). El proveedor sigue siendo
simulado (`DummyProvider`, no un modelo de lenguaje real todavía) — la
página lo deja explícito en vez de sugerir lo contrario.

El selector "Vista" (Automática/Amplia/Compacta) se obtiene llamando a
layout.render_view_mode_selector() — la misma función que usan 'Resumen
General', 'Mercado', 'Indicadores' y 'Señales', no una construcción
propia.
"""

import streamlit as st

from src.dashboard.components import (
    render_ai_availability,
    render_ai_explanation,
    render_ai_history_chart,
    render_ai_history_table,
    render_ai_metrics,
    render_ai_status,
    render_not_available,
)
from src.dashboard.layout import is_compact, render_view_mode_selector
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title("Recomendaciones de IA")
    st.caption(f"Última recomendación de IA y su historial para {symbol}.")

    view_mode = render_view_mode_selector()
    compact = is_compact(view_mode)

    page = service.get_ai_recommendations_page(exchange, symbol, limit=limit)

    if not page.data_available or page.summary is None:
        render_not_available(page.message or f"Todavía no hay recomendaciones de IA para {symbol}.")
        return

    render_ai_status(page.summary)
    render_ai_metrics(page.summary, compact=compact)
    st.divider()
    render_ai_explanation(page.summary)
    st.divider()
    render_ai_history_chart(page.history, symbol=page.selected_symbol)
    render_ai_history_table(page.history)
    st.divider()
    render_ai_availability(page.summary)
