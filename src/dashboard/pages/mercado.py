"""
Página 'Mercado' (Etapa 5, Iteración 5.4 — funcional y responsive).

Muestra, para el símbolo elegido en la barra lateral (selector compartido
en app.py), el precio más reciente, su variación frente al registro
anterior, el máximo y el mínimo del período disponible, el volumen del
último dato, la fecha de la última consulta, la cantidad de registros
disponibles y el historial de precio en un gráfico de línea.

Todo lo que se muestra viene de service.get_market_page(): esta página no
llama al repositorio, no ejecuta SQL, no recalcula indicadores/señales/
recomendaciones de IA y no se conecta a Binance. El selector "Vista"
(Automática/Amplia/Compacta) se obtiene llamando a
layout.render_view_mode_selector() — la misma función que usa 'Resumen
General', no una construcción propia — guardado solo en
st.session_state.
"""

import streamlit as st

from src.dashboard.components import (
    render_market_availability,
    render_market_metrics,
    render_not_available,
    render_price_history_chart,
)
from src.dashboard.layout import is_compact, render_view_mode_selector
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title("Mercado")
    st.caption(f"Historial de precio y disponibilidad de datos para {symbol}.")

    # Selector de vista responsive: construido íntegramente por
    # layout.render_view_mode_selector() (compartido con 'Resumen General'),
    # no por esta página. El modo elegido se conserva al navegar entre
    # páginas; solo vive en st.session_state, nunca en disco ni en
    # config.yaml.
    view_mode = render_view_mode_selector()
    compact = is_compact(view_mode)

    page = service.get_market_page(exchange, symbol, limit=limit)

    if not page.data_available or page.summary is None:
        render_not_available(page.message or f"Todavía no hay precios guardados para {symbol}.")
        return

    render_market_metrics(page.summary, compact=compact)
    st.divider()
    render_price_history_chart(page.history, symbol=page.selected_symbol)
    st.divider()
    render_market_availability(page.summary)
