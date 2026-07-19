"""
Formateo de valores para mostrar en el Dashboard (Etapa 5).

Funciones puras: reciben un valor ya obtenido (de un modelo Pydantic) y
devuelven el texto a mostrar. Ninguna calcula nada de negocio, solo dan
formato. 'N/D' (No Disponible) es el texto usado para representar
ausencia de datos, el mismo que ya usan los logs del proyecto (ver
src/services/indicator_service.py).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

NOT_AVAILABLE = "N/D"


def format_price(value: Optional[float], decimals: int = 4) -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{value:,.{decimals}f}"


def format_percent(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{value:+.{decimals}f}%"


def format_timestamp(value: Optional[datetime]) -> str:
    if value is None:
        return NOT_AVAILABLE
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_enum(value: Optional[object]) -> str:
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)
