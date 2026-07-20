"""
Helpers de (de)serialización para la persistencia SQLite de Paper Trading (Etapa 6.3).

Se centralizan aquí porque los 7 modelos persistidos comparten el mismo
patrón de conversión para Decimal y datetime, y repetirlo en cada
método de sqlite_repository.py sería puro ruido. Nada de este módulo
depende de sqlite3 ni de ningún modelo concreto: son funciones puras de
texto <-> Decimal/datetime.

Regla obligatoria (ver docs/ARQUITECTURA_PAPER_TRADING.md, Etapa 6.3):
todo Decimal se guarda como TEXT (`str(value)`) y se reconstruye con
`Decimal(value)` -- nunca REAL, para no perder precisión.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional


def decimal_to_text(value: Decimal) -> str:
    """str(value) preserva exactamente la representación decimal original."""
    return str(value)


def text_to_decimal(value: str) -> Decimal:
    return Decimal(value)


def optional_decimal_to_text(value: Optional[Decimal]) -> Optional[str]:
    return str(value) if value is not None else None


def optional_text_to_decimal(value: Optional[str]) -> Optional[Decimal]:
    return Decimal(value) if value is not None else None


def datetime_to_text(value: datetime) -> str:
    """.isoformat() preserva la zona horaria (ver Paso 9 de la Etapa 6.3)."""
    return value.isoformat()


def text_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def optional_datetime_to_text(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def optional_text_to_datetime(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value is not None else None
