"""
Página 'Paper Trading' (Etapa 6.6 — estrictamente read-only).

Muestra el estado de la cuenta simulada de Paper Trading: saldo,
patrimonio, PnL realizado/no realizado, posiciones, órdenes,
ejecuciones, trades cerrados, evolución del patrimonio/PnL y auditoría
de consistencia del PnL realizado.

Esta página NO puede ejecutar, crear, cancelar ni modificar ninguna
orden: no importa PaperTradingApplication ni PaperTradingService (el de
ejecución, Etapa 6.4), no genera IDs, no llama a ningún motor, no abre
sqlite3 directamente. Todo lo que se muestra viene de
`PaperTradingDashboardService.get_page()` (Etapa 6.6, solo lectura).
"""

from typing import Optional

import streamlit as st

from src.dashboard.charts import bar_chart, line_chart
from src.dashboard.components import render_kpi_card, render_not_available, render_section_header, render_status_badge
from src.dashboard.formatters import NOT_AVAILABLE, format_enum, format_price, format_record_count, format_timestamp
from src.dashboard.layout import render_responsive_metric_group
from src.dashboard.paper_trading_models import (
    PNL_CONSISTENT,
    PNL_INCONSISTENT,
    PNL_SUMMARY_ALL_CONSISTENT,
    PNL_SUMMARY_HAS_INCONSISTENCIES,
    PaperTradingPageView,
)
from src.dashboard.paper_trading_service import PaperTradingDashboardService
from src.dashboard.theme import COLOR_NEGATIVE, COLOR_NEUTRAL, COLOR_POSITIVE
from src.paper_trading.enums import OrderStatus

_CONSISTENCY_COLORS = {
    PNL_CONSISTENT: COLOR_POSITIVE,
    PNL_INCONSISTENT: COLOR_NEGATIVE,
}

_SUMMARY_COLORS = {
    PNL_SUMMARY_ALL_CONSISTENT: COLOR_POSITIVE,
    PNL_SUMMARY_HAS_INCONSISTENCIES: COLOR_NEGATIVE,
}


def render(service: PaperTradingDashboardService) -> None:
    st.title("Paper Trading")
    st.caption(
        "Vista de **solo lectura** de la cuenta simulada de Paper Trading: "
        "no ejecuta, crea, cancela ni modifica ninguna orden."
    )

    if not service.enabled:
        st.warning(
            "Paper Trading está deshabilitado en la configuración "
            "(`paper_trading.enabled: false`). Los datos históricos, si existen, "
            "siguen disponibles para consulta."
        )

    exchange, symbol, status, limit, include_flat = _render_filters()

    page = service.get_page(
        exchange=exchange, symbol=symbol, status=status, limit=limit, include_flat=include_flat,
    )

    if not page.initialized:
        render_not_available(page.message or "Paper Trading aún no ha sido inicializado.")
        return

    _render_overview(page)
    st.divider()
    _render_consistency_section(page)
    st.divider()

    tab_positions, tab_orders, tab_executions, tab_trades, tab_charts = st.tabs(
        ["Posiciones", "Órdenes", "Ejecuciones", "Trades", "Gráficos"]
    )
    with tab_positions:
        _render_positions_table(page)
    with tab_orders:
        _render_orders_table(page)
    with tab_executions:
        _render_executions_table(page)
    with tab_trades:
        _render_trades_table(page)
    with tab_charts:
        _render_charts(page)


def _render_filters() -> tuple[Optional[str], Optional[str], Optional[OrderStatus], int, bool]:
    """Filtros propios de esta página (no comparten estado con el
    selector de símbolo de las demás páginas, que es sobre market_data,
    un concepto distinto): exchange, símbolo, estado de orden, límite de
    historial e incluir/excluir posiciones FLAT. Ninguno modifica la
    base -- son solo parámetros de lectura de la siguiente consulta."""
    with st.expander("Filtros", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            exchange_input = st.text_input("Exchange", value="", help="Vacío = todos los exchanges.")
            status_label = st.selectbox("Estado de orden", ["Todos"] + [s.value for s in OrderStatus])
        with col_b:
            symbol_input = st.text_input("Símbolo", value="", help="Vacío = todos los símbolos.")
            limit = st.slider("Registros de historial", min_value=1, max_value=1000, value=100)
        include_flat = st.checkbox("Incluir posiciones cerradas (FLAT)", value=False)

    exchange = exchange_input.strip() or None
    symbol = symbol_input.strip().upper() or None
    status = None if status_label == "Todos" else OrderStatus(status_label)
    return exchange, symbol, status, limit, include_flat


def _render_overview(page: PaperTradingPageView) -> None:
    overview = page.overview
    render_section_header(
        "Resumen de la cuenta",
        f"Moneda: {overview.currency} · Paper Trading "
        f"{'habilitado' if overview.enabled else 'deshabilitado'}.",
    )

    render_responsive_metric_group(
        [
            ("Saldo total", format_price(overview.total_balance)),
            ("Saldo reservado", format_price(overview.reserved_balance)),
            ("Saldo disponible", format_price(overview.available_balance)),
        ],
        compact=False,
    )
    render_responsive_metric_group(
        [
            ("Valor de posiciones", format_price(overview.positions_value)),
            ("Patrimonio total", format_price(overview.total_equity)),
            ("PnL no realizado", format_price(overview.unrealized_pnl_total)),
        ],
        compact=False,
    )
    render_responsive_metric_group(
        [
            ("PnL realizado acumulado", format_price(overview.realized_pnl_cumulative)),
            ("Posiciones abiertas", format_record_count(overview.open_positions_count)),
            ("Trades totales", format_record_count(overview.total_trades_count)),
        ],
        compact=False,
    )

    if not overview.has_snapshot:
        st.caption("Sin snapshot de cartera disponible todavía — los valores de arriba muestran N/D.")
    else:
        st.caption(f"Último snapshot: {format_timestamp(overview.last_snapshot_at)}.")


def _render_consistency_section(page: PaperTradingPageView) -> None:
    render_section_header("Consistencia del PnL realizado")
    summary = page.overview.pnl_consistency_summary
    render_status_badge(summary, _SUMMARY_COLORS.get(summary, COLOR_NEUTRAL))

    if not page.consistency_rows:
        render_not_available("No hay posiciones ni trades para validar todavía.")
        return

    rows = [
        {
            "Exchange": row.exchange,
            "Símbolo": row.symbol,
            "PnL de la posición": format_price(row.position_realized_pnl),
            "PnL calculado desde Trades": format_price(row.calculated_realized_pnl),
            "Estado": row.status,
        }
        for row in page.consistency_rows
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_positions_table(page: PaperTradingPageView) -> None:
    if not page.positions:
        render_not_available("No hay posiciones para mostrar con los filtros actuales.")
        return

    rows = [
        {
            "Exchange": p.exchange,
            "Símbolo": p.symbol,
            "Lado": format_enum(p.side),
            "Cantidad": format_price(p.quantity, decimals=8),
            "Cantidad reservada": format_price(p.reserved_quantity, decimals=8),
            "Precio promedio de entrada": format_price(p.average_entry_price),
            "PnL realizado acumulado": format_price(p.realized_pnl_to_date),
            "Fecha de apertura": format_timestamp(p.opened_at),
            "Última actualización": format_timestamp(p.updated_at),
            "Consistencia PnL": p.pnl_consistency,
        }
        for p in page.positions
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_orders_table(page: PaperTradingPageView) -> None:
    if not page.orders:
        render_not_available("No hay órdenes para mostrar con los filtros actuales.")
        return

    rows = [
        {
            "ID": o.id,
            "Creada": format_timestamp(o.created_at),
            "Actualizada": format_timestamp(o.updated_at),
            "Exchange": o.exchange,
            "Símbolo": o.symbol,
            "Side": format_enum(o.side),
            "Tipo": format_enum(o.order_type),
            "Cantidad": format_price(o.quantity, decimals=8),
            "Cantidad ejecutada": format_price(o.filled_quantity, decimals=8),
            "Precio promedio": format_price(o.average_fill_price),
            "Estado": format_enum(o.status),
            "Fuente": format_enum(o.source),
            "Recomendación vinculada": o.linked_recommendation_id or NOT_AVAILABLE,
            "Motivo de rechazo": o.rejection_reason or NOT_AVAILABLE,
            "Motivo de cancelación": o.cancellation_reason or NOT_AVAILABLE,
        }
        for o in page.orders
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_executions_table(page: PaperTradingPageView) -> None:
    if not page.executions:
        render_not_available("No hay ejecuciones para mostrar con los filtros actuales.")
        return

    rows = [
        {
            "Execution ID": e.id,
            "Order ID": e.order_id,
            "Fecha ejecución": format_timestamp(e.executed_at),
            "Exchange": e.exchange,
            "Símbolo": e.symbol,
            "Cantidad": format_price(e.quantity, decimals=8),
            "Precio": format_price(e.price),
            "Fee": format_price(e.fee),
            "Notional (presentación)": format_price(e.notional),
        }
        for e in page.executions
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_trades_table(page: PaperTradingPageView) -> None:
    if not page.trades:
        render_not_available("No hay trades cerrados para mostrar con los filtros actuales.")
        return

    rows = [
        {
            "Trade ID": t.id,
            "Apertura": format_timestamp(t.opened_at),
            "Cierre": format_timestamp(t.closed_at),
            "Exchange": t.exchange,
            "Símbolo": t.symbol,
            "Side": format_enum(t.side),
            "Cantidad": format_price(t.quantity, decimals=8),
            "Precio entrada": format_price(t.entry_price),
            "Precio salida": format_price(t.exit_price),
            "PnL bruto": format_price(t.gross_pnl),
            "Fees": format_price(t.fees),
            "PnL neto": format_price(t.net_pnl),
            "Exit Execution ID": t.exit_execution_id,
        }
        for t in page.trades
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_charts(page: PaperTradingPageView) -> None:
    if not page.equity_history:
        render_not_available("Todavía no hay snapshots de cartera para graficar.")
    else:
        # Conversión a float solo en este último paso, exigido por Plotly
        # (ver Paso 17): Decimal se mantuvo en todo el resto de la capa.
        timestamps = [point.timestamp for point in page.equity_history]
        st.plotly_chart(
            line_chart(
                timestamps, [float(point.total_equity) for point in page.equity_history],
                title="Evolución del patrimonio total",
            ),
            use_container_width=True,
        )
        st.plotly_chart(
            line_chart(
                timestamps, [float(point.realized_pnl_cumulative) for point in page.equity_history],
                title="Evolución del PnL realizado acumulado",
            ),
            use_container_width=True,
        )
        st.plotly_chart(
            line_chart(
                timestamps, [float(point.unrealized_pnl_total) for point in page.equity_history],
                title="Evolución del PnL no realizado",
            ),
            use_container_width=True,
        )

    if not page.symbol_pnl_distribution:
        render_not_available("Todavía no hay trades cerrados para distribuir PnL por símbolo.")
        return

    labels = [f"{item.exchange}:{item.symbol}" for item in page.symbol_pnl_distribution]
    values = [float(item.net_pnl_sum) for item in page.symbol_pnl_distribution]
    st.plotly_chart(
        bar_chart(labels, values, title="Distribución del PnL neto por símbolo"),
        use_container_width=True,
    )
