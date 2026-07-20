"""
MarketPriceProvider -- abstracción del precio actual para Paper Trading (Etapa 6.5).

Adapta la infraestructura de mercado ya existente (`MarketDataRepository`,
Etapa 1) a lo que Paper Trading necesita: un precio como `Decimal`,
nunca `float`, nunca inventado. `RepositoryMarketPriceProvider` no abre
ninguna conexión nueva a un exchange: solo lee el último `MarketTicker`
ya persistido por el ciclo existente (`MarketDataService`, ver
src/main.py) a través de la interfaz `MarketDataRepository` ya aprobada
(src/database/base.py) -- exactamente el mismo repositorio que ya
consume `DashboardRepository` (src/dashboard/repository.py).
"""

from decimal import Decimal
from typing import Protocol

from src.database.base import MarketDataRepository


class MarketPriceProvider(Protocol):
    """Interfaz mínima que PaperTradingApplication necesita para conocer precios."""

    def get_current_price(self, exchange: str, symbol: str) -> Decimal:
        """Devuelve el precio actual de (exchange, symbol) como Decimal > 0.

        Debe fallar (ValueError) si no hay ningún precio disponible o si
        el precio disponible no es válido -- nunca inventa un precio.
        """
        ...

    def get_current_prices(
        self, symbols: list[tuple[str, str]]
    ) -> dict[tuple[str, str], Decimal]:
        """Igual que get_current_price(), para varios símbolos a la vez."""
        ...


class RepositoryMarketPriceProvider:
    """Adaptador real: consulta el último `MarketTicker` vía `MarketDataRepository`.

    `MarketTicker.price` es `float` (ver src/models/market_data.py); la
    conversión a Decimal pasa siempre por `Decimal(str(value))`, nunca
    `Decimal(value)` directamente sobre un float (que arrastraría el
    error de representación binaria del float en vez de sus dígitos
    decimales visibles).
    """

    def __init__(self, market_repository: MarketDataRepository):
        self._market_repository = market_repository

    def get_current_price(self, exchange: str, symbol: str) -> Decimal:
        tickers = self._market_repository.fetch_by_symbol(exchange, symbol, limit=1)
        if not tickers:
            raise ValueError(f"No hay ningún precio persistido para {exchange}:{symbol}.")

        price = Decimal(str(tickers[-1].price))
        if price <= 0:
            raise ValueError(
                f"El último precio persistido para {exchange}:{symbol} no es válido: {price}."
            )
        return price

    def get_current_prices(
        self, symbols: list[tuple[str, str]]
    ) -> dict[tuple[str, str], Decimal]:
        return {
            (exchange, symbol): self.get_current_price(exchange, symbol)
            for exchange, symbol in symbols
        }
