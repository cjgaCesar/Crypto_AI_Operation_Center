"""
Punto de entrada del Dashboard (Etapa 5).

Ejecutar con:  streamlit run src/dashboard/app.py

Este archivo SOLO arma las piezas (configuración, repositorio, servicio) y
decide qué página renderizar según la selección del usuario en la barra
lateral — el mismo espíritu de Composition Root que src/main.py para el
bot. Ninguna lógica de negocio ni de consulta vive aquí: eso está en
service.py/repository.py.
"""

import streamlit as st

from src.dashboard.config import DashboardConfig, build_dashboard_config
from src.dashboard.filters import validate_limit
from src.dashboard.pages import (
    estado_tecnico,
    indicadores,
    mercado,
    paper_trading,
    recomendaciones,
    resumen,
    senales,
)
from src.dashboard.paper_trading_repository import RepositoryPaperTradingDashboardRepository
from src.dashboard.paper_trading_service import PaperTradingDashboardService
from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.utils.config import load_settings

_PAGE_RESUMEN = "Resumen General"
_PAGE_MERCADO = "Mercado"
_PAGE_INDICADORES = "Indicadores"
_PAGE_SENALES = "Señales"
_PAGE_RECOMENDACIONES = "Recomendaciones de IA"
_PAGE_ESTADO_TECNICO = "Estado Técnico"
_PAGE_PAPER_TRADING = "Paper Trading"

_PAGE_NAMES = [
    _PAGE_RESUMEN,
    _PAGE_MERCADO,
    _PAGE_INDICADORES,
    _PAGE_SENALES,
    _PAGE_RECOMENDACIONES,
    _PAGE_ESTADO_TECNICO,
    _PAGE_PAPER_TRADING,
]

# Páginas que no necesitan un selector de símbolo/límite en la barra lateral.
# 'Paper Trading' tiene su propio conjunto de filtros (exchange/símbolo/
# estado de orden/límite/incluir FLAT, ver pages/paper_trading.py), distinto
# del selector de símbolo de mercado que comparten el resto de páginas.
_PAGES_WITHOUT_SYMBOL_FILTER = {_PAGE_RESUMEN, _PAGE_ESTADO_TECNICO, _PAGE_PAPER_TRADING}


def _build_service_and_config() -> tuple[DashboardService, DashboardConfig, PaperTradingDashboardService]:
    settings = load_settings()
    # "Binance" es, hoy, el único exchange implementado (ver
    # BinanceExchangeClient.exchange_name en src/market/binance.py); igual
    # que en build_services() de src/main.py, se pasa explícito porque
    # Settings no lo expone directamente.
    config = build_dashboard_config(settings, exchange="Binance")
    repository = SQLiteDashboardRepository(config.database_path)
    service = DashboardService(
        repository=repository,
        exchange=config.exchange,
        symbols=config.symbols,
        default_history_limit=config.default_history_limit,
        max_history_limit=config.max_history_limit,
    )

    # Deliberadamente NO se llama build_paper_trading_context() aquí: esa
    # función ejecuta repository.init() y siembra el capital inicial (Etapa
    # 6.5), efectos que este Dashboard de solo lectura nunca debe producir
    # (ver Paso 21 de la Etapa 6.6). Se construye únicamente el repositorio
    # de escritura sin llamar a ningún método de escritura, envuelto en el
    # adaptador de solo lectura de esta etapa.
    paper_trading_repository = SQLitePaperTradingRepository(settings.paper_trading.database_path)
    paper_trading_dashboard_repository = RepositoryPaperTradingDashboardRepository(
        paper_trading_repository, settings.paper_trading.database_path,
    )
    paper_trading_service = PaperTradingDashboardService(
        repository=paper_trading_dashboard_repository,
        enabled=settings.paper_trading.enabled,
        currency=settings.paper_trading.currency,
        default_history_limit=config.default_history_limit,
        max_history_limit=config.max_history_limit,
    )

    return service, config, paper_trading_service


def main() -> None:
    st.set_page_config(page_title="Crypto AI Operation Center — Dashboard", layout="wide")

    try:
        service, config, paper_trading_service = _build_service_and_config()
    except Exception as exc:
        st.error(f"No se pudo cargar la configuración del proyecto: {exc}")
        return

    st.sidebar.title("Crypto AI Operation Center")
    st.sidebar.caption(
        "Dashboard de **solo lectura**: no ejecuta operaciones, no modifica "
        "ningún dato, no recalcula indicadores/señales/recomendaciones."
    )

    status = service.get_system_status()
    if not status.database_exists:
        st.sidebar.warning(
            f"La base de datos todavía no existe ({status.database_path}). "
            "Ejecuta `python -m src.main` al menos un ciclo primero."
        )

    page_name = st.sidebar.radio("Página", _PAGE_NAMES)

    symbol = None
    limit = config.default_history_limit
    if page_name not in _PAGES_WITHOUT_SYMBOL_FILTER:
        symbol = st.sidebar.selectbox("Símbolo", config.symbols)
        raw_limit = st.sidebar.slider(
            "Registros de historial",
            min_value=1,
            max_value=config.max_history_limit,
            value=config.default_history_limit,
        )
        limit = validate_limit(
            raw_limit, default=config.default_history_limit, maximum=config.max_history_limit,
        )

    try:
        if page_name == _PAGE_RESUMEN:
            resumen.render(service, exchange=config.exchange)
        elif page_name == _PAGE_ESTADO_TECNICO:
            estado_tecnico.render(service)
        elif page_name == _PAGE_MERCADO:
            mercado.render(service, exchange=config.exchange, symbol=symbol, limit=limit)
        elif page_name == _PAGE_INDICADORES:
            indicadores.render(service, exchange=config.exchange, symbol=symbol, limit=limit)
        elif page_name == _PAGE_SENALES:
            senales.render(service, exchange=config.exchange, symbol=symbol, limit=limit)
        elif page_name == _PAGE_RECOMENDACIONES:
            recomendaciones.render(service, exchange=config.exchange, symbol=symbol, limit=limit)
        elif page_name == _PAGE_PAPER_TRADING:
            paper_trading.render(paper_trading_service)
    except Exception as exc:
        st.error(f"Ocurrió un error al mostrar esta página: {exc}")


if __name__ == "__main__":
    main()
