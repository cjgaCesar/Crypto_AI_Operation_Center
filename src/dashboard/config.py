"""
Configuración del Dashboard (Etapa 5).

DashboardConfig agrupa los valores que el Dashboard necesita: la mayoría
vienen de Settings (src/utils/config.py, ya cargado desde config.yaml +
.env), y un puñado son propios del Dashboard con un valor por defecto
interno (no se agregó ninguna sección nueva a config.yaml para esta
iteración, ver docs/ALCANCE_ETAPA_5.md): son valores de presentación
(cada cuánto refrescar, cuántos registros mostrar), no umbrales de
negocio como los que sí viven en 'signals'/'ai' dentro de config.yaml.
"""

from dataclasses import dataclass

from src.utils.config import Settings

# Valores por defecto propios del Dashboard. Si en una iteración futura
# se decide que deban ser configurables desde config.yaml, agregar una
# sección 'dashboard:' siguiendo el mismo patrón que 'signals'/'ai'.
DEFAULT_REFRESH_INTERVAL_SECONDS = 30
DEFAULT_HISTORY_LIMIT = 100
MAX_HISTORY_LIMIT = 1000


@dataclass(frozen=True)
class DashboardConfig:
    database_path: str
    symbols: list[str]
    exchange: str
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS
    default_history_limit: int = DEFAULT_HISTORY_LIMIT
    max_history_limit: int = MAX_HISTORY_LIMIT


def build_dashboard_config(settings: Settings, exchange: str) -> DashboardConfig:
    """Arma la configuración del Dashboard a partir de un Settings ya
    cargado (load_settings()). 'exchange' se recibe explícito, igual que
    en build_services() de src/main.py, porque Settings no lo expone
    directamente: hoy siempre es BinanceExchangeClient.exchange_name, el
    único exchange implementado."""
    return DashboardConfig(
        database_path=settings.database.sqlite_path,
        symbols=settings.symbols,
        exchange=exchange,
    )
