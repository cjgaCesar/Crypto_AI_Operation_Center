"""
Validación y normalización de filtros del Dashboard (Etapa 5).

Funciones puras, sin Streamlit ni SQLite: reciben un valor ya ingresado
(por un selector de la UI o por una llamada directa) y devuelven una
versión válida/normalizada. No consultan nada ni dependen de ningún otro
módulo del Dashboard.
"""

from typing import Optional


def normalize_symbol(symbol: str) -> str:
    """Recorta espacios y pasa a mayúsculas (formato que usa Binance,
    ej. 'btcusdt' -> 'BTCUSDT'). Un símbolo vacío es un error de
    programación (no una ausencia de datos), por eso se lanza ValueError
    en vez de devolver un valor por defecto silencioso."""
    if not symbol or not symbol.strip():
        raise ValueError("El símbolo no puede estar vacío.")
    return symbol.strip().upper()


def normalize_exchange(exchange: str) -> str:
    """Recorta espacios. Un exchange vacío es un error de programación."""
    if not exchange or not exchange.strip():
        raise ValueError("El exchange no puede estar vacío.")
    return exchange.strip()


def validate_limit(limit: Optional[int], default: int, maximum: int) -> int:
    """Devuelve un límite de historial siempre válido (nunca <= 0, nunca
    mayor a 'maximum'). A diferencia de normalize_symbol/normalize_exchange,
    aquí NO se lanza una excepción: un límite inválido no es un error fatal,
    es una entrada de la UI que conviene corregir en silencio para que el
    Dashboard nunca se rompa por un valor fuera de rango."""
    if limit is None or limit <= 0:
        return default
    return min(limit, maximum)
