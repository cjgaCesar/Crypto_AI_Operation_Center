"""
Página 'Resumen General' (Etapa 5, Iteración 5.3 — funcional y responsive).

Primera página completamente funcional del Dashboard: muestra, para cada
símbolo configurado, una tarjeta con precio, variación 24h, señal, score,
confianza de la señal, recomendación de IA, confianza de IA, riesgo y
última actualización, además de un resumen del estado general del
sistema. Todo lo que se muestra viene de service.get_summary_view() /
service.get_system_status(): esta página no llama al repositorio, no
ejecuta SQL, no recalcula nada y no se conecta a Binance ni a ningún
proveedor de IA.

El layout (cuántas tarjetas por fila, columnas o apiladas) lo decide
src/dashboard/layout.py según el modo de vista elegido en la barra
lateral (Automática/Amplia/Compacta), guardado solo en
st.session_state — nunca en disco ni en config.yaml.
"""

import streamlit as st

from src.dashboard.components import render_not_available, render_summary_card
from src.dashboard.formatters import format_relative_status
from src.dashboard.layout import (
    VIEW_MODE_AUTO,
    VIEW_MODE_HELP_TEXT,
    VIEW_MODE_SESSION_KEY,
    VIEW_MODES,
    get_cards_per_row,
    is_compact,
    render_responsive_grid,
)
from src.dashboard.service import DashboardService


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

    # Selector de vista responsive: se agrega desde esta página (no desde
    # app.py) para no tocar la navegación general por algo específico de
    # "Resumen General". Comparte VIEW_MODE_SESSION_KEY y VIEW_MODE_HELP_TEXT
    # con 'Mercado' (ver layout.py): el modo elegido se conserva al navegar
    # entre páginas. Solo vive en st.session_state, nunca se escribe a disco
    # ni a config.yaml.
    view_mode = st.sidebar.selectbox(
        "Vista", VIEW_MODES, index=VIEW_MODES.index(VIEW_MODE_AUTO), key=VIEW_MODE_SESSION_KEY,
        help=VIEW_MODE_HELP_TEXT,
    )
    cards_per_row = get_cards_per_row(view_mode)
    compact = is_compact(view_mode)

    render_responsive_grid(
        views, lambda view: render_summary_card(view, compact=compact), cards_per_row,
    )
