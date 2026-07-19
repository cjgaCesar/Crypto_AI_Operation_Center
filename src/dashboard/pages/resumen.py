"""
Página 'Resumen General' (Etapa 5, Iteración 5.3 — funcional).

Primera página completamente funcional del Dashboard: muestra, para cada
símbolo configurado, una tarjeta con precio, variación 24h, señal, score,
confianza de la señal, recomendación de IA, confianza de IA, riesgo y
última actualización, además de un resumen del estado general del
sistema. Todo lo que se muestra viene de service.get_summary_view() /
service.get_system_status(): esta página no llama al repositorio, no
ejecuta SQL, no recalcula nada y no se conecta a Binance ni a ningún
proveedor de IA.
"""

import streamlit as st

from src.dashboard.components import render_not_available, render_summary_card
from src.dashboard.formatters import format_relative_status
from src.dashboard.service import DashboardService

# Máximo de tarjetas por fila (Bloque 9: layout ancho, jerarquía clara).
_MAX_CARDS_PER_ROW = 3


def render(service: DashboardService, exchange: str) -> None:
    st.title("Resumen General")
    st.caption("Estado más reciente del mercado, señales e IA.")

    status = service.get_system_status()
    if not status.database_exists:
        render_not_available(
            f"La base de datos todavía no existe ({status.database_path}). "
            "Ejecuta `python -m src.main` al menos un ciclo primero."
        )
        return

    views = service.get_summary_view(exchange=exchange)

    if not views:
        render_not_available("No hay símbolos configurados todavía.")
        return

    complete_views = [
        v for v in views if v.has_market_data and v.has_signal_data and v.has_ai_data
    ]
    latest_timestamps = [v.latest_update_timestamp for v in views if v.latest_update_timestamp]
    system_latest_timestamp = max(latest_timestamps) if latest_timestamps else None

    status_col1, status_col2, status_col3 = st.columns(3)
    with status_col1:
        st.metric("Símbolos configurados", len(views))
    with status_col2:
        st.metric("Símbolos con datos completos", f"{len(complete_views)}/{len(views)}")
    with status_col3:
        st.metric("Última actualización del sistema", format_relative_status(system_latest_timestamp))

    # Estados vacíos parciales: cuál es el eslabón más temprano de la
    # cadena (mercado -> señales -> IA) que todavía no tiene ningún dato.
    if not any(v.has_market_data for v in views):
        st.warning("Todavía no hay precios guardados para ningún símbolo configurado.")
    elif not any(v.has_signal_data for v in views):
        st.info("Hay precios disponibles, pero todavía no se generó ninguna señal.")
    elif not any(v.has_ai_data for v in views):
        st.info(
            "Hay señales disponibles, pero todavía no hay recomendaciones de IA "
            "(revisa si `ai.enabled` está en `true` en config.yaml)."
        )

    st.divider()

    for row_start in range(0, len(views), _MAX_CARDS_PER_ROW):
        row_views = views[row_start:row_start + _MAX_CARDS_PER_ROW]
        columns = st.columns(_MAX_CARDS_PER_ROW)
        for column, view in zip(columns, row_views):
            with column:
                render_summary_card(view)
