"""
Implementación futura de MarketDataRepository usando PostgreSQL.

Este archivo NO se usa todavía en ningún lugar del proyecto. Se deja
preparado para una etapa futura, cuando se decida migrar de SQLite a
PostgreSQL (por ejemplo, para producción o para manejar mayor volumen de
datos o accesos concurrentes).

Para activarlo en el futuro, sin tener que rediseñar nada:
1. Agregar un driver de PostgreSQL a requirements.txt (ej. psycopg2-binary).
2. Implementar cada método usando ese driver, con la URL de conexión que ya
   se lee desde la variable de entorno DATABASE_URL (ver src/utils/config.py
   y .env.example).
3. Instanciar PostgresMarketDataRepository en vez de SQLiteMarketDataRepository
   en el punto donde se arma la aplicación (hoy en src/main.py), sin tocar
   nada más: servicios, modelos y el resto del proyecto no cambian, porque
   ambos repositorios cumplen la misma interfaz MarketDataRepository.

La tabla equivalente deberá incluir las mismas columnas que usa hoy
SQLiteMarketDataRepository: exchange, symbol, price, volume_24h,
price_change_percent_24h y queried_at (ver MarketTicker en
src/models/market_data.py).
"""

from src.database.base import MarketDataRepository
from src.models.market_data import MarketTicker

_NOT_IMPLEMENTED_MSG = (
    "PostgresMarketDataRepository todavía no está implementado. "
    "Es solo la estructura preparada para una etapa futura de migración "
    "desde SQLite. Ver docs/ARQUITECTURA.md."
)


class PostgresMarketDataRepository(MarketDataRepository):
    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def init(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def save(self, tickers: list[MarketTicker]) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def fetch_all(self) -> list[MarketTicker]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
