"""
Componentes visuales reutilizables del Dashboard (Etapa 5).

Helpers pequeños que envuelven llamadas de Streamlit. A diferencia de
repository.py/service.py/filters.py/formatters.py/theme.py (que no
dependen de Streamlit a propósito), este módulo sí lo hace: es la única
capa de presentación reutilizada entre páginas.

Usa únicamente componentes nativos de Streamlit (container, columns,
metric, caption, markdown, info, warning) — sin CSS complejo ni
animaciones. El único HTML insertado (en render_status_badge) es un
`<span>` con un color controlado por theme.py sobre texto que siempre
viene de un Enum ya validado por Pydantic (nunca texto libre externo ni
entrada de usuario), por lo que no representa un riesgo de inyección.
"""

from typing import Optional

import streamlit as st

from src.dashboard.formatters import (
    format_confidence,
    format_enum,
    format_percent,
    format_price_compact,
    format_relative_status,
    format_risk_level,
    format_score,
)
from src.dashboard.models import DashboardSummaryView
from src.dashboard.theme import COLOR_AI, get_change_color, get_risk_color, get_signal_color


def render_not_available(message: str = "Sin datos disponibles todavía.") -> None:
    """Mensaje estándar de 'dato no disponible', usado en toda página
    cuando el Service devuelve None o una lista vacía."""
    st.info(message)


def render_kpi_card(label: str, value: str, help_text: Optional[str] = None) -> None:
    """Tarjeta KPI básica: un valor destacado con su etiqueta. Envuelve
    st.metric; no compara todavía contra un valor anterior (Iteración 5.4)."""
    st.metric(label=label, value=value, help=help_text)


def render_section_header(title: str, subtitle: Optional[str] = None) -> None:
    """Encabezado de sección reutilizable: título + subtítulo opcional
    (más chico que st.title, para separar secciones dentro de una página)."""
    st.markdown(f"#### {title}")
    if subtitle:
        st.caption(subtitle)


def render_status_badge(label: str, color: str) -> None:
    """Insignia de una sola línea con color de fondo (ej. 'Bullish' en
    verde). 'label' y 'color' siempre vienen de datos ya validados
    (Enums de dominio, constantes de theme.py), nunca de texto libre
    externo, por lo que insertarlos en un bloque de markdown controlado
    es seguro."""
    st.markdown(
        f'<span style="background-color:{color}22; color:{color}; '
        f'padding:2px 10px; border-radius:6px; font-weight:600; font-size:0.85rem;">'
        f"{label}</span>",
        unsafe_allow_html=True,
    )


def render_data_availability(
    has_market: bool, has_indicators: bool, has_signal: bool, has_ai: bool
) -> None:
    """Fila compacta indicando qué tablas tienen datos para este símbolo
    (mercado/indicadores/señales/IA), con un ✅/❌ por cada una."""
    parts = [
        ("Mercado", has_market),
        ("Indicadores", has_indicators),
        ("Señales", has_signal),
        ("IA", has_ai),
    ]
    st.caption(" · ".join(f"{'✅' if ok else '❌'} {name}" for name, ok in parts))


def render_summary_card(view: DashboardSummaryView) -> None:
    """Tarjeta de resumen de un símbolo para la página 'Resumen General':
    precio, variación 24h, señal, score, confianza de señal, recomendación
    de IA, confianza de IA, riesgo, última actualización y disponibilidad
    de datos. Usa únicamente componentes nativos de Streamlit."""
    with st.container(border=True):
        render_section_header(view.symbol)

        price_col, change_col = st.columns(2)
        with price_col:
            render_kpi_card("Precio", format_price_compact(view.price))
        with change_col:
            st.caption("Variación 24h")
            render_status_badge(
                format_percent(view.price_change_percent_24h),
                get_change_color(view.price_change_percent_24h),
            )

        signal_col, score_col, signal_conf_col = st.columns(3)
        with signal_col:
            st.caption("Señal")
            render_status_badge(format_enum(view.signal_type), get_signal_color(view.signal_type))
        with score_col:
            render_kpi_card("Score", format_score(view.signal_score))
        with signal_conf_col:
            render_kpi_card("Confianza señal", format_enum(view.signal_confidence))

        ai_col, ai_conf_col, risk_col = st.columns(3)
        with ai_col:
            st.caption("Recomendación IA")
            render_status_badge(format_enum(view.ai_recommendation), COLOR_AI)
        with ai_conf_col:
            render_kpi_card("Confianza IA", format_confidence(view.ai_confidence))
        with risk_col:
            st.caption("Riesgo")
            render_status_badge(format_risk_level(view.ai_risk_level), get_risk_color(view.ai_risk_level))

        st.caption(f"Última actualización: {format_relative_status(view.latest_update_timestamp)}")
        render_data_availability(
            view.has_market_data, view.has_indicator_data, view.has_signal_data, view.has_ai_data,
        )
