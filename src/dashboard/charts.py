"""
Gráficos del Dashboard (Etapa 5).

Iteración 5.2 (estructura base): solo existen un gráfico de línea genérico
y una figura de "sin datos". Los gráficos históricos completos (precio +
indicadores superpuestos, score/confidence en el tiempo, etc.) se
implementan en la Iteración 5.3. Ninguna función de este archivo conoce
SQLite, Streamlit ni los modelos del proyecto: reciben listas simples de
valores ya extraídos por la página.
"""

import plotly.graph_objects as go


def empty_figure(message: str = "Sin datos disponibles todavía") -> go.Figure:
    """Figura vacía con un mensaje centrado, usada como placeholder
    cuando todavía no hay historial suficiente para graficar."""
    figure = go.Figure()
    figure.add_annotation(
        text=message, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font={"size": 16},
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def line_chart(x: list, y: list, title: str = "") -> go.Figure:
    """Gráfico de línea genérico: una serie (x, y) con un título. Si no
    hay datos, devuelve empty_figure() en vez de un gráfico vacío
    confuso."""
    if not x or not y:
        return empty_figure()

    figure = go.Figure(data=go.Scatter(x=x, y=y, mode="lines"))
    figure.update_layout(title=title)
    return figure


def multi_line_chart(x: list, series: dict, title: str = "") -> go.Figure:
    """Gráfico de línea con varias series superpuestas (ej. MACD/Señal/
    Histograma, o SMA/EMA rápida/media/lenta), una traza por clave de
    'series' (nombre -> lista de valores, misma longitud que 'x').
    Valores None dentro de una serie dejan un hueco en esa línea (ej. una
    media que todavía no tiene suficiente historial) en vez de fallar.
    Si 'x' está vacío o ninguna serie tiene valores, devuelve
    empty_figure()."""
    if not x or not any(series.values()):
        return empty_figure()

    figure = go.Figure()
    for name, y in series.items():
        if y:
            figure.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name))
    figure.update_layout(title=title)
    return figure


def bar_chart(labels: list, values: list, title: str = "") -> go.Figure:
    """Gráfico de barras genérico: una barra por (label, value) -- ej.
    distribución de PnL neto por símbolo (Etapa 6.6). Si no hay datos,
    devuelve empty_figure() en vez de un gráfico vacío confuso."""
    if not labels or not values:
        return empty_figure()

    figure = go.Figure(data=go.Bar(x=labels, y=values))
    figure.update_layout(title=title)
    return figure
