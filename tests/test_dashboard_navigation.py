"""
Pruebas de integración entre páginas del Dashboard (Etapa 5, Iteración
5.4 — cierre): usando streamlit.testing.v1.AppTest, valida que el modo de
vista responsive ("Vista": Automática/Amplia/Compacta) se comparte entre
'Resumen General' y 'Mercado' a través de layout.VIEW_MODE_SESSION_KEY,
en vez de mantenerse por separado en cada página.

El harness reproduce el mismo enrutamiento de src/dashboard/app.py (un
radio de página + despacho a resumen.render()/mercado.render()), pero
recibe un DashboardService ya construido en vez de llamar a
load_settings()/build_dashboard_config(): así la prueba queda hermética
(base SQLite temporal), sin depender de config.yaml/.env ni de la base
de datos real del proyecto.

Nota: el radio del harness usa la etiqueta ASCII "Pagina" (sin tilde),
a propósito. AppTest.from_function() reconstruye el código fuente de la
función y lo re-ejecuta en un script temporal; en este entorno Windows,
un literal con tilde escrito directamente en esa función (ej. "Pagina"
con tilde) hace que el widget correspondiente no aparezca en el árbol
de elementos, sin lanzar ninguna excepción capturable (bug de
codificación de from_function, no del Dashboard: confirmado con una
reproducción mínima aislada). No afecta a los literales reales de
resumen.py/mercado.py/app.py, que se leen normalmente del disco (ya
validados por separado con AppTest.from_file() contra la app real).
"""

from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from src.dashboard.repository import SQLiteDashboardRepository
from src.dashboard.service import DashboardService
from src.database.sqlite_repository import SQLiteMarketDataRepository
from src.models.market_data import MarketTicker

_PAGE_RESUMEN = "Resumen General"
_PAGE_MERCADO = "Mercado"


def _ticker(symbol="BTCUSDT", price=100.0) -> MarketTicker:
    return MarketTicker(
        exchange="Binance", symbol=symbol, price=price, volume_24h=10.0,
        price_change_percent_24h=1.5, queried_at=datetime.now(timezone.utc),
    )


def _service_for(db_path: str, symbols=("BTCUSDT", "ETHUSDT")) -> DashboardService:
    repository = SQLiteDashboardRepository(db_path)
    return DashboardService(
        repository=repository, exchange="Binance", symbols=list(symbols),
        default_history_limit=100, max_history_limit=1000,
    )


def _populated_db(tmp_path, symbols=("BTCUSDT", "ETHUSDT")) -> str:
    db_path = str(tmp_path / "populated.db")
    repo = SQLiteMarketDataRepository(db_path)
    repo.init()
    for symbol in symbols:
        repo.save([_ticker(symbol=symbol, price=100.0)])
        repo.save([_ticker(symbol=symbol, price=105.0)])
    return db_path


def _render_app(service, exchange, symbol):
    import streamlit as st

    from src.dashboard.pages import mercado, resumen

    page_name = st.sidebar.radio("Pagina", ["Resumen General", "Mercado"])

    if page_name == "Resumen General":
        resumen.render(service, exchange=exchange)
    elif page_name == "Mercado":
        mercado.render(service, exchange=exchange, symbol=symbol, limit=100)


def _run(service, exchange="Binance", symbol="BTCUSDT", timeout=30):
    at = AppTest.from_function(_render_app, args=(service, exchange, symbol))
    at.run(timeout=timeout)
    return at


def _radio(at):
    return next(r for r in at.sidebar.radio if r.label == "Pagina")


def _vista(at):
    return next(sb for sb in at.sidebar.selectbox if sb.label == "Vista")


def test_app_loads_without_exceptions(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception


def test_resumen_general_loads_by_default(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception
    assert at.title[0].value == "Resumen General"


def test_vista_selector_is_available(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    assert not at.exception
    assert len(at.sidebar.selectbox) == 1
    assert _vista(at).label == "Vista"


def test_only_one_vista_selector_at_a_time(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    _radio(at).set_value("Mercado").run(timeout=30)
    assert not at.exception
    vista_selectors = [sb for sb in at.sidebar.selectbox if sb.label == "Vista"]
    assert len(vista_selectors) == 1


def test_view_mode_persists_when_navigating_between_pages(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    # 1. Elegir "Compacta" en Resumen General.
    _vista(at).select("Compacta").run(timeout=30)
    assert not at.exception
    assert _vista(at).value == "Compacta"

    # 2. Navegar a Mercado: debe conservar "Compacta" (misma key
    # compartida vía layout.VIEW_MODE_SESSION_KEY).
    _radio(at).set_value("Mercado").run(timeout=30)
    assert not at.exception
    assert at.title[0].value == "Mercado"
    assert _vista(at).value == "Compacta"

    # 3. Cambiar a "Amplia" en Mercado.
    _vista(at).select("Amplia").run(timeout=30)
    assert not at.exception
    assert _vista(at).value == "Amplia"

    # 4. Volver a Resumen General: debe conservar "Amplia".
    _radio(at).set_value("Resumen General").run(timeout=30)
    assert not at.exception
    assert at.title[0].value == "Resumen General"
    assert _vista(at).value == "Amplia"

    # 5. Repetir con "Automática".
    _vista(at).select("Automática").run(timeout=30)
    assert not at.exception
    assert _vista(at).value == "Automática"

    _radio(at).set_value("Mercado").run(timeout=30)
    assert not at.exception
    assert _vista(at).value == "Automática"


def test_full_navigation_flow_has_zero_exceptions(tmp_path):
    db_path = _populated_db(tmp_path)
    at = _run(_service_for(db_path))

    steps = [
        lambda: _vista(at).select("Compacta").run(timeout=30),
        lambda: _radio(at).set_value("Mercado").run(timeout=30),
        lambda: _vista(at).select("Amplia").run(timeout=30),
        lambda: _radio(at).set_value("Resumen General").run(timeout=30),
        lambda: _vista(at).select("Automática").run(timeout=30),
        lambda: _radio(at).set_value("Mercado").run(timeout=30),
        lambda: _radio(at).set_value("Resumen General").run(timeout=30),
    ]
    for step in steps:
        step()
        assert not at.exception
