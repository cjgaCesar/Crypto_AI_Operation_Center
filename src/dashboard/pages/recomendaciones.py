"""
Página 'Recomendaciones de IA' (Etapa 5, Iteración 5.2 — esqueleto).

La Iteración 5.3 mostrará el historial completo y el detalle de
reasoning/advantages/risks. Por ahora solo confirma que la última
recomendación se puede leer.
"""

import streamlit as st

from src.dashboard.components import render_not_available
from src.dashboard.formatters import format_enum, format_timestamp
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title(f"Recomendaciones de IA — {symbol}")
    st.caption("Estructura base (Iteración 5.2) — sin historial completo todavía.")

    history = service.get_ai_view(exchange, symbol, limit=1)
    recommendation = history[-1] if history else None

    if recommendation is None:
        render_not_available(f"Todavía no hay recomendaciones de IA para {symbol}.")
        return

    st.write(f"Recomendación: {format_enum(recommendation.recommendation)}")
    st.write(f"Confianza: {recommendation.confidence:.2f}%")
    st.write(f"Generado: {format_timestamp(recommendation.timestamp)}")
