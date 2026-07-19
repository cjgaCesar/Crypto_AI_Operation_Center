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

from src.dashboard.charts import line_chart, multi_line_chart
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
from src.dashboard.models import (
    AIRecommendationSummaryView,
    DashboardSummaryView,
    IndicatorSummaryView,
    MarketHistoryPoint,
    MarketSummaryView,
    SignalSummaryView,
)
from src.ai.recommendation import AIRecommendation
from src.models.indicator_data import IndicatorSnapshot
from src.models.signal_data import SignalSnapshot
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


def render_indicator_metrics(summary: IndicatorSummaryView, compact: bool) -> None:
    """Métricas principales de la página 'Indicadores': RSI, MACD (línea/
    señal/histograma), medias móviles (SMA, EMA rápida/media/lenta),
    Bandas de Bollinger (superior/media/inferior) y VWAP. Cada valor
    ausente (todavía no calculado, ej. EMA lenta necesita 200 lecturas)
    se muestra como 'N/D' vía formatters — nunca se recalcula ni se
    inventa aquí."""
    metrics = [
        ("RSI", format_price(summary.rsi, decimals=2)),
        ("MACD", format_price(summary.macd_line, decimals=4)),
        ("Señal MACD", format_price(summary.macd_signal, decimals=4)),
        ("Histograma MACD", format_price(summary.macd_histogram, decimals=4)),
        ("SMA", format_price(summary.sma)),
        ("EMA rápida", format_price(summary.ema_fast)),
        ("EMA media", format_price(summary.ema_medium)),
        ("EMA lenta", format_price(summary.ema_slow)),
        ("Banda superior", format_price(summary.bollinger_upper)),
        ("Banda media", format_price(summary.bollinger_middle)),
        ("Banda inferior", format_price(summary.bollinger_lower)),
        ("VWAP", format_price(summary.vwap)),
    ]
    render_responsive_metric_group(metrics, compact=compact)


def render_indicator_availability(summary: Optional[IndicatorSummaryView]) -> None:
    """Fecha del último cálculo, y una nota explícita de que ATR, ADX y
    Volatilidad todavía no existen en 'market_indicators' (no se calculan
    en ninguna etapa de este proyecto, ver README) — se declaran "N/D" en
    vez de omitirse en silencio, para que quede claro que no es un olvido
    de esta página sino una limitación real del proyecto."""
    if summary is None:
        st.caption("Sin datos disponibles todavía.")
    else:
        st.caption(f"Último cálculo: {format_timestamp(summary.calculated_at)}")
    st.caption(
        f"ATR: {NOT_AVAILABLE} · ADX: {NOT_AVAILABLE} · Volatilidad: {NOT_AVAILABLE} "
        "(no calculados todavía en este proyecto)"
    )


def render_indicator_history_charts(history: list[IndicatorSnapshot], symbol: str) -> None:
    """3 gráficos de historial de indicadores, a ancho completo del
    contenedor: RSI, MACD (línea/señal/histograma superpuestos) y medias
    móviles (SMA + EMA rápida/media/lenta superpuestas). Con historial
    vacío o de un solo registro, charts.line_chart()/multi_line_chart()
    ya devuelven una figura vacía o de un punto sin fallar; valores None
    dentro de una serie (indicador todavía sin suficiente historial)
    dejan un hueco en esa línea en vez de romper el gráfico."""
    timestamps = [snapshot.calculated_at for snapshot in history]

    rsi_figure = line_chart(
        timestamps, [snapshot.rsi for snapshot in history], title=f"RSI — {symbol}",
    )
    st.plotly_chart(rsi_figure, use_container_width=True)

    macd_figure = multi_line_chart(
        timestamps,
        {
            "MACD": [snapshot.macd_line for snapshot in history],
            "Señal": [snapshot.macd_signal for snapshot in history],
            "Histograma": [snapshot.macd_histogram for snapshot in history],
        },
        title=f"MACD — {symbol}",
    )
    st.plotly_chart(macd_figure, use_container_width=True)

    moving_averages_figure = multi_line_chart(
        timestamps,
        {
            "SMA": [snapshot.sma for snapshot in history],
            "EMA rápida": [snapshot.ema_fast for snapshot in history],
            "EMA media": [snapshot.ema_medium for snapshot in history],
            "EMA lenta": [snapshot.ema_slow for snapshot in history],
        },
        title=f"Medias móviles — {symbol}",
    )
    st.plotly_chart(moving_averages_figure, use_container_width=True)


def render_signal_status(summary: SignalSummaryView) -> None:
    """Señal principal (insignia de color, siempre en su propia línea —
    es lo prioritario), vía theme.get_signal_color()."""
    st.caption("Señal")
    render_status_badge(format_enum(summary.signal_type), get_signal_color(summary.signal_type))


def render_signal_metrics(summary: SignalSummaryView, compact: bool) -> None:
    """Score, confianza y tendencia (con su fuerza) de la señal actual,
    vía render_responsive_metric_group()."""
    metrics = [
        ("Score", format_score(summary.score)),
        ("Confianza", format_enum(summary.confidence)),
        ("Tendencia", format_enum(summary.trend)),
        ("Fuerza de tendencia", format_enum(summary.trend_strength)),
    ]
    render_responsive_metric_group(metrics, compact=compact)


def render_signal_explanation(summary: SignalSummaryView, compact: bool) -> None:
    """Veredicto de cada componente (EMA/MACD/RSI/Bollinger) que explica
    la señal agregada. Solo el resultado de cada regla (ej. 'Bullish
    Cross'); el detalle en texto ('reason') de cada una vive en
    SignalSnapshot pero no se muestra aquí para no sobrecargar el
    resumen — sigue disponible en el historial subyacente si una
    iteración futura decide exponerlo."""
    metrics = [
        ("EMA", format_enum(summary.ema_signal)),
        ("MACD", format_enum(summary.macd_signal)),
        ("RSI", format_enum(summary.rsi_signal)),
        ("Bollinger", format_enum(summary.bollinger_signal)),
    ]
    render_responsive_metric_group(metrics, compact=compact)


def render_signal_availability(summary: Optional[SignalSummaryView]) -> None:
    """Fecha de generación de la última señal + cantidad de registros
    disponibles. El riesgo no se menciona aquí: no es un campo de
    'market_signals' (vive en 'ai_recommendations', página
    'Recomendaciones de IA', todavía no implementada) — es un concepto
    de una página distinta, no un dato ausente de esta."""
    if summary is None:
        st.caption("Sin datos disponibles todavía.")
        return
    st.caption(
        f"Generado: {format_timestamp(summary.generated_at)} · "
        f"Registros disponibles: {format_record_count(summary.record_count)}"
    )
    st.caption(
        "El riesgo no aplica a esta página: vive en 'Recomendaciones de "
        "IA' (todavía no implementada), no en 'market_signals'."
    )


def render_signal_history_chart(history: list[SignalSnapshot], symbol: str) -> None:
    """Gráfico de línea de la evolución del score (valor numérico
    continuo, sin inventar una escala para las categorías). El
    historial de señal/confianza/tendencia (categóricos) se muestra por
    separado en render_signal_history_table(), no en este gráfico."""
    timestamps = [snapshot.generated_at for snapshot in history]
    scores = [snapshot.score for snapshot in history]
    figure = line_chart(timestamps, scores, title=f"Score de señal — {symbol}")
    st.plotly_chart(figure, use_container_width=True)


def render_signal_history_table(history: list[SignalSnapshot]) -> None:
    """Historial cronológico (más reciente primero) de señal/confianza/
    tendencia/score como tabla, no como gráfico: señal/confianza/
    tendencia son categóricas, y representarlas como números arbitrarios
    en un eje sería engañoso. `st.dataframe(..., use_container_width=True)`:
    sin ancho fijo, sin scroll horizontal forzado."""
    if not history:
        return
    rows = [
        {
            "Fecha": format_timestamp(snapshot.generated_at),
            "Señal": format_enum(snapshot.signal_type),
            "Confianza": format_enum(snapshot.confidence),
            "Tendencia": format_enum(snapshot.trend),
            "Score": format_score(snapshot.score),
        }
        for snapshot in reversed(history)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_ai_status(summary: AIRecommendationSummaryView) -> None:
    """Recomendación actual (insignia de color, propia línea). Usa
    theme.COLOR_AI (color fijo), mismo criterio ya establecido en
    'Resumen General' para la insignia de recomendación de IA: no varía
    según la acción sugerida (a diferencia de la señal, que sí tiene un
    color por SignalType)."""
    st.caption("Recomendación")
    render_status_badge(format_enum(summary.recommendation), COLOR_AI)


def render_ai_metrics(summary: AIRecommendationSummaryView, compact: bool) -> None:
    """Confianza (métrica) + riesgo (insignia de color, vía
    theme.get_risk_color(), propia línea)."""
    render_responsive_metric_group(
        [("Confianza", format_confidence(summary.confidence))], compact=compact,
    )
    st.caption("Riesgo")
    render_status_badge(format_risk_level(summary.risk_level), get_risk_color(summary.risk_level))


def render_ai_explanation(summary: AIRecommendationSummaryView) -> None:
    """Resumen en una línea + razonamiento/ventajas/riesgos completos en
    un expander (detalle expandible, ideal para móvil: no ocupa espacio
    hasta que el usuario lo abre)."""
    st.caption("Resumen")
    st.write(summary.summary or NOT_AVAILABLE)
    with st.expander("Razonamiento completo"):
        st.write(summary.reasoning or NOT_AVAILABLE)
        if summary.advantages:
            st.write("**Ventajas:**")
            for advantage in summary.advantages:
                st.write(f"- {advantage}")
        if summary.risks:
            st.write("**Riesgos:**")
            for risk in summary.risks:
                st.write(f"- {risk}")


def render_ai_availability(summary: Optional[AIRecommendationSummaryView]) -> None:
    """Fecha de generación + cantidad de registros + proveedor/modelo,
    dejando explícito que hoy es un proveedor simulado (no un modelo de
    lenguaje real) — para no sugerir que la recomendación viene de una
    IA real todavía."""
    if summary is None:
        st.caption("Sin datos disponibles todavía.")
        return
    st.caption(
        f"Generado: {format_timestamp(summary.timestamp)} · "
        f"Registros disponibles: {format_record_count(summary.record_count)}"
    )
    st.caption(
        f"Proveedor: {summary.provider or NOT_AVAILABLE} · "
        f"Modelo: {summary.model or NOT_AVAILABLE} "
        "(simulado — todavía no es un modelo de lenguaje real)"
    )


def render_ai_history_chart(history: list[AIRecommendation], symbol: str) -> None:
    """Gráfico de línea de la evolución de la confianza (valor numérico
    continuo 0-100). El historial de recomendación/riesgo (categóricos)
    se muestra por separado en render_ai_history_table(), no en este
    gráfico."""
    timestamps = [recommendation.timestamp for recommendation in history]
    confidences = [recommendation.confidence for recommendation in history]
    figure = line_chart(timestamps, confidences, title=f"Confianza de IA — {symbol}")
    st.plotly_chart(figure, use_container_width=True)


def render_ai_history_table(history: list[AIRecommendation]) -> None:
    """Historial cronológico (más reciente primero) de recomendación/
    confianza/riesgo como tabla, no como gráfico: recomendación y riesgo
    son categóricos, y representarlos como números arbitrarios en un eje
    sería engañoso."""
    if not history:
        return
    rows = [
        {
            "Fecha": format_timestamp(recommendation.timestamp),
            "Recomendación": format_enum(recommendation.recommendation),
            "Confianza": format_confidence(recommendation.confidence),
            "Riesgo": format_risk_level(recommendation.risk_level),
        }
        for recommendation in reversed(history)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
