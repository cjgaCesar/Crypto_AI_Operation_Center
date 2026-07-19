"""
Página 'Resumen General' (Etapa 5, Iteración 5.2 — esqueleto).

La Iteración 5.3 mostrará una tarjeta KPI por símbolo (precio, señal y
recomendación de IA más recientes). Por ahora solo confirma que el
Service responde y lista los símbolos configurados.
"""

import streamlit as st

from src.dashboard.components import render_not_available
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str) -> None:
    st.title("Resumen General")
    st.caption("Estructura base (Iteración 5.2) — sin tarjetas KPI todavía.")

    summaries = service.get_summary(exchange=exchange)

    if not summaries:
        render_not_available("No hay símbolos configurados todavía.")
        return

    st.write(f"Símbolos configurados: {', '.join(s.symbol for s in summaries)}")
