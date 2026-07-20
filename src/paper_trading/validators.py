"""
Invariantes de dominio compartidas entre los modelos de Paper Trading.

Cada modelo (models.py) valida sus propios campos con @model_validator,
pero varios modelos repiten exactamente el mismo patrón de comparación
(ej. "un campo no puede superar a otro", "un campo debe ser None
exactamente cuando se cumple una condición"). Centralizar esas dos
comprobaciones aquí evita repetir la misma lógica de comparación en
cada modelo y permite testearla de forma aislada.
"""

from decimal import Decimal
from typing import Optional


def ensure_le(value: Decimal, limit: Decimal, value_name: str, limit_name: str) -> None:
    """Levanta ValueError si value > limit.

    Usado por Order.filled_quantity <= quantity, Position.reserved_quantity
    <= quantity y CashBalance.reserved_balance <= total_balance.
    """
    if value > limit:
        raise ValueError(f"{value_name} ({value}) no puede superar {limit_name} ({limit})")


def ensure_none_iff(
    value: Optional[Decimal], condition: bool, value_name: str, condition_description: str,
) -> None:
    """Levanta ValueError salvo que (value es None) sea exactamente igual a condition.

    Usado por Order.average_fill_price (None solo si filled_quantity == 0)
    y Position.average_entry_price (None solo si side == FLAT).
    """
    if condition and value is not None:
        raise ValueError(f"{value_name} debe ser None cuando {condition_description}")
    if not condition and value is None:
        raise ValueError(f"{value_name} es obligatorio cuando no se cumple: {condition_description}")
