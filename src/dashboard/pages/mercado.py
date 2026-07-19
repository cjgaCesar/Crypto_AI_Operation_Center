"""
Página 'Precios' (Etapa 5, Iteración 5.2 — esqueleto).

La Iteración 5.3 mostrará el historial de precio con SMA/EMA superpuestos.
Por ahora solo confirma que el último precio se puede leer.
"""

import streamlit as st

from src.dashboard.components import render_not_available
from src.dashboard.formatters import format_price, format_timestamp
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title(f"Precios — {symbol}")
    st.caption("Estructura base (Iteración 5.2) — sin gráfico histórico todavía.")

    history = service.get_market_view(exchange, symbol, limit=1)
    ticker = history[-1] if history else None

    if ticker is None:
        render_not_available(f"Todavía no hay precios guardados para {symbol}.")
        return

    st.write(f"Último precio: {format_price(ticker.price)}")
    st.write(f"Consultado: {format_timestamp(ticker.queried_at)}")
