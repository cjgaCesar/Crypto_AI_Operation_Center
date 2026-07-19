"""
Cliente para consultar datos PÚBLICOS de mercado en Binance.

Implementa la interfaz ExchangeClient (src/market/base.py) para que el resto
del proyecto pueda tratar a Binance igual que a cualquier otro exchange que
se agregue en el futuro.

Usa únicamente el endpoint público /api/v3/ticker/24hr: no requiere API key
ni autenticación. Los parámetros api_key/api_secret se guardan para poder
usarlos en endpoints privados de una etapa futura, pero NO se usan todavía.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

import requests

from src.market.base import ExchangeClient, ExchangeClientError
from src.models.market_data import MarketTicker

logger = logging.getLogger(__name__)


class BinanceClientError(ExchangeClientError):
    """Error al consultar la API pública de Binance."""


class BinanceExchangeClient(ExchangeClient):
    exchange_name = "Binance"

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 10,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        # Reservados para futuros endpoints privados de Binance. No se usan todavía.
        self.api_key = api_key
        self.api_secret = api_secret

    def get_ticker_24hr(self, symbol: str) -> MarketTicker:
        """Consulta el resumen de 24 horas de un símbolo (ej. 'BTCUSDT')."""
        url = f"{self.base_url}/api/v3/ticker/24hr"
        params = {"symbol": symbol}

        try:
            response = requests.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("Error al consultar Binance para %s: %s", symbol, exc)
            raise BinanceClientError(f"No se pudo consultar {symbol}: {exc}") from exc

        try:
            return MarketTicker(
                exchange=self.exchange_name,
                symbol=data["symbol"],
                price=float(data["lastPrice"]),
                volume_24h=float(data["volume"]),
                price_change_percent_24h=float(data["priceChangePercent"]),
                queried_at=datetime.now(timezone.utc),
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("Respuesta inesperada de Binance para %s: %s", symbol, data)
            raise BinanceClientError(
                f"Respuesta inesperada de Binance para {symbol}: {exc}"
            ) from exc

    def get_tickers(self, symbols: list[str]) -> list[MarketTicker]:
        """Consulta varios símbolos uno por uno.

        Si uno falla, se registra el error y se continúa con los demás en
        lugar de detener todo el ciclo por un solo símbolo.
        """
        results = []
        for symbol in symbols:
            try:
                results.append(self.get_ticker_24hr(symbol))
            except BinanceClientError:
                continue
        return results
