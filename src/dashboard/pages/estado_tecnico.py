"""
Página 'Estado Técnico' (Etapa 5, Iteración 5.2).

Muestra el estado de las 4 tablas SQLite (existe, cuántas filas, cuál es
el registro más reciente). No depende de gráficos ni de un símbolo
específico, por lo que ya queda completamente funcional en esta iteración.
"""

import streamlit as st

from src.dashboard.formatters import format_timestamp
from src.dashboard.service import DashboardService


def render(service: DashboardService) -> None:
    st.title("Estado Técnico")
    st.caption("Diagnóstico de solo lectura de la base SQLite del proyecto.")

    status = service.get_system_status()

    if not status.database_exists:
        st.warning(f"La base de datos todavía no existe: {status.database_path}")
        return

    for table in status.tables:
        if not table.exists:
            st.write(f"❌ {table.table_name}: tabla todavía no creada.")
            continue
        st.write(
            f"✅ {table.table_name}: {table.row_count} filas — "
            f"último registro: {format_timestamp(table.latest_timestamp)}"
        )
