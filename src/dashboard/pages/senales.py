"""
Página 'Señales' (Etapa 5, Iteración 5.2 — esqueleto).

La Iteración 5.3 mostrará el historial de score/confidence y el detalle
de cada regla. Por ahora solo confirma que la última señal se puede leer.
"""

import streamlit as st

from src.dashboard.components import render_not_available
from src.dashboard.formatters import format_enum, format_price, format_timestamp
from src.dashboard.service import DashboardService


def render(service: DashboardService, exchange: str, symbol: str, limit: int) -> None:
    st.title(f"Señales — {symbol}")
    st.caption("Estructura base (Iteración 5.2) — sin historial completo todavía.")

    history = service.get_signals_view(exchange, symbol, limit=1)
    signal = history[-1] if history else None

    if signal is None:
        render_not_available(f"Todavía no hay señales generadas para {symbol}.")
        return

    st.write(f"Signal type: {format_enum(signal.signal_type)}")
    st.write(f"Score: {format_price(signal.score, decimals=2)}")
    st.write(f"Generado: {format_timestamp(signal.generated_at)}")
