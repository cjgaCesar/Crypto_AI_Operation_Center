"""
Formateo de valores para mostrar en el Dashboard (Etapa 5).

Funciones puras: reciben un valor ya obtenido (de un modelo Pydantic) y
devuelven el texto a mostrar. Ninguna calcula nada de negocio, ni cambia
el dato original (solo lo formatean como texto); ninguna asigna color
(eso vive en src/dashboard/theme.py, a propósito, para no mezclar
formato de texto con presentación visual). 'N/D' (No Disponible) es el
texto usado para representar ausencia de datos, el mismo que ya usan los
logs del proyecto (ver src/services/indicator_service.py).
"""

from datetime import datetime, timezone
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


def format_price_compact(value: Optional[float], decimals: int = 2) -> str:
    """Precio con separador de miles, más compacto que format_price()
    (menos decimales por defecto): pensado para tarjetas KPI, donde el
    espacio es limitado y no se necesita la precisión completa."""
    if value is None:
        return NOT_AVAILABLE
    return f"{value:,.{decimals}f}"


def format_confidence(value: Optional[float], decimals: int = 0) -> str:
    """Confianza (0-100) como porcentaje simple, sin signo +/- (a
    diferencia de format_percent, que es para variaciones, no para un
    nivel de confianza que siempre es un valor informativo, no un cambio)."""
    if value is None:
        return NOT_AVAILABLE
    return f"{value:.{decimals}f}%"


def format_score(value: Optional[float], decimals: int = 2) -> str:
    """Score (0-100) como número simple, sin símbolo de porcentaje ni
    signo: es un puntaje, no una variación ni una probabilidad."""
    if value is None:
        return NOT_AVAILABLE
    return f"{value:.{decimals}f}"


def format_risk_level(value: Optional[object]) -> str:
    """Nivel de riesgo (RiskLevel u otro Enum) como texto legible.
    Delegado a format_enum: mismo criterio (.value si es Enum), con un
    nombre propio para que el código que llama sea más claro sobre qué
    está formateando."""
    return format_enum(value)


def format_relative_status(
    timestamp: Optional[datetime], reference: Optional[datetime] = None
) -> str:
    """Texto relativo ('Hace 5 min') a partir de un timestamp, comparado
    contra 'reference' (por defecto, el instante actual en UTC). Recibir
    'reference' explícito permite que las pruebas sean deterministas, sin
    depender del reloj real de la máquina."""
    if timestamp is None:
        return NOT_AVAILABLE

    if reference is None:
        reference = datetime.now(timezone.utc)

    seconds = (reference - timestamp).total_seconds()
    if seconds < 60:
        return "Hace instantes"

    minutes = int(seconds // 60)
    if minutes < 60:
        return f"Hace {minutes} min"

    hours = int(minutes // 60)
    if hours < 24:
        return f"Hace {hours} h"

    days = int(hours // 24)
    return f"Hace {days} d"
