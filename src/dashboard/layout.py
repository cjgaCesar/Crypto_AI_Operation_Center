"""
Helpers de layout responsive del Dashboard (Etapa 5, Iteración 5.3).

Streamlit no expone de forma confiable el ancho real del viewport (no hay
breakpoints dinámicos nativos equivalentes a CSS moderno, y este proyecto
explícitamente no agrega detección de viewport vía JavaScript ni paquetes
de terceros para lograrlo). La estrategia adoptada es conservadora y
explícita: el usuario elige un modo de vista (Automática/Amplia/Compacta)
desde un selector en la barra lateral, guardado únicamente en
`st.session_state` (nunca en disco ni en config.yaml), y ese modo
determina cuántas tarjetas se muestran por fila y si cada tarjeta usa
columnas o layout vertical apilado.

Este módulo es independiente de DashboardRepository y DashboardService:
no ejecuta SQL, no sabe nada de las 4 tablas ni de los modelos de dominio.
Puede usar Streamlit (es capa de presentación, igual que components.py),
pero no agrega ninguna dependencia nueva.
"""

from typing import Callable, Sequence, TypeVar

import streamlit as st

VIEW_MODE_AUTO = "Automática"
VIEW_MODE_WIDE = "Amplia"
VIEW_MODE_COMPACT = "Compacta"

VIEW_MODES = [VIEW_MODE_AUTO, VIEW_MODE_WIDE, VIEW_MODE_COMPACT]

# Tarjetas por fila según el modo de vista. Nunca 0, nunca más de 3.
# 'Automática' usa un valor conservador intermedio (2): ni tan ancho como
# para verse apretado en una pantalla mediana, ni tan angosto como para
# desperdiciar espacio en un escritorio grande.
_CARDS_PER_ROW = {
    VIEW_MODE_WIDE: 3,
    VIEW_MODE_COMPACT: 1,
    VIEW_MODE_AUTO: 2,
}

T = TypeVar("T")


def get_cards_per_row(view_mode: str) -> int:
    """Cuántas tarjetas mostrar por fila según el modo de vista. Un modo
    desconocido (incluyendo None) cae en el mismo valor que 'Automática'
    — nunca 0, nunca más de 3."""
    return _CARDS_PER_ROW.get(view_mode, _CARDS_PER_ROW[VIEW_MODE_AUTO])


def is_compact(view_mode: str) -> bool:
    """Si el modo de vista debe usar layout vertical apilado (una
    tarjeta/grupo por fila) en vez de columnas lado a lado."""
    return view_mode == VIEW_MODE_COMPACT


def render_responsive_grid(
    items: Sequence[T], render_item: Callable[[T], None], cards_per_row: int
) -> None:
    """Distribuye 'items' en filas de 'cards_per_row' columnas, llamando a
    render_item(item) dentro de cada columna. Con cards_per_row <= 1
    (modo compacto), renderiza cada item de corrido sin crear columnas: el
    resultado visual es el mismo (una columna ocupa el 100% del ancho
    disponible), pero evita la indirección innecesaria."""
    if cards_per_row <= 1:
        for item in items:
            render_item(item)
        return

    for row_start in range(0, len(items), cards_per_row):
        row_items = items[row_start:row_start + cards_per_row]
        columns = st.columns(cards_per_row)
        for column, item in zip(columns, row_items):
            with column:
                render_item(item)


def render_responsive_metric_group(metrics: Sequence[tuple], compact: bool) -> None:
    """Renderiza un grupo de (label, value) como columnas lado a lado (no
    compacto) o apiladas verticalmente (compacto), siempre con st.metric.
    Evita que cada sección de la tarjeta reimplemente la misma rama
    compact/no-compact."""
    if compact or len(metrics) <= 1:
        for label, value in metrics:
            st.metric(label=label, value=value)
        return

    columns = st.columns(len(metrics))
    for column, (label, value) in zip(columns, metrics):
        with column:
            st.metric(label=label, value=value)
