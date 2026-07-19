"""
Componentes visuales reutilizables del Dashboard (Etapa 5).

Helpers pequeños que envuelven llamadas de Streamlit. A diferencia de
repository.py/service.py/filters.py/formatters.py/theme.py (que no
dependen de Streamlit a propósito), este módulo sí lo hace: es la única
capa de presentación reutilizada entre páginas.

Usa únicamente componentes nativos de Streamlit (container, columns,
metric, caption, markdown, info, warning) — sin CSS complejo, sin HTML
(ningún `unsafe_allow_html`) ni animaciones. render_status_badge() usa la
sintaxis nativa de markdown de Streamlit para texto coloreado
(":color-background[texto]", ver src/dashboard/theme.py) en vez de HTML.
"""

from typing import Optional

import streamlit as st

from src.dashboard.charts import line_chart
from src.dashboard.formatters import (
    NOT_AVAILABLE,
    format_confidence,
    format_enum,
    format_percent,
    format_price,
    format_price_change,
    format_price_compact,
    format_record_count,
    format_relative_status,
    format_risk_level,
    format_score,
    format_timestamp,
    format_volume,
)
from src.dashboard.layout import render_responsive_metric_group
from src.dashboard.models import DashboardSummaryView, MarketHistoryPoint, MarketSummaryView
from src.dashboard.theme import (
    COLOR_AI,
    get_change_color,
    get_risk_color,
    get_signal_color,
    to_streamlit_color_name,
)


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


def render_status_badge(label: Optional[str], color: Optional[str]) -> None:
    """Insignia de una sola línea con color de fondo (ej. 'Bullish' en
    verde), usando la sintaxis nativa de Streamlit para texto coloreado
    (":color-background[texto]"), sin HTML ni `unsafe_allow_html`.

    'label' y 'color' siempre deberían venir de datos ya validados
    (Enums de dominio vía formatters, constantes de theme.py), nunca de
    texto libre externo — pero esta función se protege a sí misma de
    todas formas: un label vacío/None se muestra como "N/D"
    (formatters.NOT_AVAILABLE), y un color no reconocido cae en gris
    neutral (theme.to_streamlit_color_name). Los corchetes se escapan
    para no romper la sintaxis de markdown si algún valor llegara a
    contenerlos."""
    safe_label = (label or NOT_AVAILABLE).replace("[", "(").replace("]", ")")
    color_name = to_streamlit_color_name(color)
    st.markdown(f":{color_name}-background[{safe_label}]")


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


def _render_market_section(view: DashboardSummaryView, compact: bool) -> None:
    """Precio + variación 24h. En modo compacto, apilados; si no, en 2
    columnas. El precio es un st.metric; la variación es una insignia de
    color (positiva/negativa/neutral vía theme.get_change_color)."""
    if compact:
        render_kpi_card("Precio", format_price_compact(view.price))
        st.caption("Variación 24h")
        render_status_badge(
            format_percent(view.price_change_percent_24h),
            get_change_color(view.price_change_percent_24h),
        )
        return

    price_col, change_col = st.columns(2)
    with price_col:
        render_kpi_card("Precio", format_price_compact(view.price))
    with change_col:
        st.caption("Variación 24h")
        render_status_badge(
            format_percent(view.price_change_percent_24h),
            get_change_color(view.price_change_percent_24h),
        )


def _render_signal_section(view: DashboardSummaryView, compact: bool) -> None:
    """Señal (insignia, siempre en su propia línea — es lo prioritario)
    + score/confianza de la señal (grupo de métricas secundarias,
    columnas o apiladas según 'compact')."""
    st.caption("Señal")
    render_status_badge(format_enum(view.signal_type), get_signal_color(view.signal_type))
    render_responsive_metric_group(
        [
            ("Score", format_score(view.signal_score)),
            ("Confianza señal", format_enum(view.signal_confidence)),
        ],
        compact=compact,
    )


def _render_ai_section(view: DashboardSummaryView, compact: bool) -> None:
    """Recomendación de IA (insignia, propia línea) + confianza de IA
    (métrica secundaria) + riesgo (insignia, propia línea)."""
    st.caption("Recomendación IA")
    render_status_badge(format_enum(view.ai_recommendation), COLOR_AI)
    render_responsive_metric_group(
        [("Confianza IA", format_confidence(view.ai_confidence))], compact=compact,
    )
    st.caption("Riesgo")
    render_status_badge(format_risk_level(view.ai_risk_level), get_risk_color(view.ai_risk_level))


def _render_update_section(view: DashboardSummaryView) -> None:
    """Última actualización relativa + disponibilidad de las 4 tablas.
    Información secundaria: siempre en captions, sin columnas (no hay
    nada que ganar apilándola distinto según el modo de vista)."""
    st.caption(f"Última actualización: {format_relative_status(view.latest_update_timestamp)}")
    render_data_availability(
        view.has_market_data, view.has_indicator_data, view.has_signal_data, view.has_ai_data,
    )


def render_summary_card(view: DashboardSummaryView, compact: bool = False) -> None:
    """Tarjeta de resumen de un símbolo para la página 'Resumen General':
    precio, variación 24h, señal, score, confianza de señal, recomendación
    de IA, confianza de IA, riesgo, última actualización y disponibilidad
    de datos. Usa únicamente componentes nativos de Streamlit
    (st.container(border=True), sin ancho/alto fijo).

    'compact=True' apila cada sección verticalmente (una métrica/insignia
    por fila) en vez de usar columnas lado a lado, para pantallas
    angostas — la información mostrada es exactamente la misma; solo
    cambia cómo se agrupa visualmente (ver _render_*_section)."""
    with st.container(border=True):
        render_section_header(view.symbol)
        _render_market_section(view, compact)
        _render_signal_section(view, compact)
        _render_ai_section(view, compact)
        _render_update_section(view)


def render_market_metrics(summary: MarketSummaryView, compact: bool) -> None:
    """Métricas principales de la página 'Mercado': precio actual,
    variación absoluta y porcentual frente al registro anterior, máximo y
    mínimo del período disponible, y volumen del último dato — en
    columnas lado a lado o apiladas según 'compact', igual criterio que
    render_responsive_metric_group() ya usa en 'Resumen General'."""
    metrics = [
        ("Precio actual", format_price(summary.latest_price)),
        ("Variación", format_price_change(summary.absolute_change)),
        ("Variación %", format_percent(summary.percentage_change)),
        ("Máximo del período", format_price(summary.period_high)),
        ("Mínimo del período", format_price(summary.period_low)),
    ]
    if summary.volume is not None:
        metrics.append(("Volumen", format_volume(summary.volume)))
    render_responsive_metric_group(metrics, compact=compact)


def render_market_availability(summary: Optional[MarketSummaryView]) -> None:
    """Fecha del último dato disponible y cantidad de registros del
    historial consultado (respeta el límite elegido en la barra
    lateral: no es necesariamente el total histórico de la tabla)."""
    if summary is None:
        st.caption("Sin datos disponibles todavía.")
        return
    st.caption(
        f"Último dato: {format_timestamp(summary.latest_timestamp)} · "
        f"Registros disponibles: {format_record_count(summary.record_count)}"
    )


def render_price_history_chart(history: list[MarketHistoryPoint], symbol: str) -> None:
    """Gráfico de línea del historial de precio, a ancho completo del
    contenedor (se adapta a cualquier modo de vista, sin scroll
    horizontal). Con 0 o 1 registro, charts.line_chart() ya devuelve una
    figura vacía o un único punto sin fallar."""
    timestamps = [point.timestamp for point in history]
    prices = [point.price for point in history]
    figure = line_chart(timestamps, prices, title=f"Precio histórico — {symbol}")
    st.plotly_chart(figure, use_container_width=True)
