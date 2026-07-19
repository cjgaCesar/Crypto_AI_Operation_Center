"""
Componentes visuales reutilizables del Dashboard (Etapa 5).

Helpers pequeños que envuelven llamadas de Streamlit. A diferencia de
repository.py/service.py/filters.py/formatters.py (que no dependen de
Streamlit a propósito), este módulo sí lo hace: es la única capa de
presentación reutilizada entre páginas.
"""

from typing import Optional

import streamlit as st


def render_not_available(message: str = "Sin datos disponibles todavía.") -> None:
    """Mensaje estándar de 'dato no disponible', usado en toda página
    cuando el Service devuelve None o una lista vacía."""
    st.info(message)


def render_kpi_card(label: str, value: str, help_text: Optional[str] = None) -> None:
    """Tarjeta KPI básica: un valor destacado con su etiqueta. Envuelve
    st.metric; no compara todavía contra un valor anterior (Iteración 5.3)."""
    st.metric(label=label, value=value, help=help_text)
