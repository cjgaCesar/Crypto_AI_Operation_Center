"""
Tipos de resultado devueltos por los motores puros de Paper Trading (Etapa 6.2).

Se centralizan aquí (en vez de definirse dentro de fill_engine.py /
position_engine.py) para que ambos motores -- y sus pruebas -- importen
el mismo tipo desde un único lugar, sin que fill_engine.py y
position_engine.py necesiten importarse entre sí.

NamedTuple, no BaseModel: estos no son entidades de dominio que se
persistan ni se validen (eso ya lo hicieron Order/Execution/Position/
Trade al construirse) -- son solo el resultado, inmutable, de una
llamada a un motor puro.
"""

from decimal import Decimal
from typing import NamedTuple, Optional

from src.paper_trading.models import Execution, Order, Position, Trade


class FillResult(NamedTuple):
    """Resultado de FillEngine.execute_market_order: Order actualizada + Execution generada."""

    order: Order
    execution: Execution


class PositionUpdateResult(NamedTuple):
    """Resultado de PositionEngine.apply_execution.

    trade es None cuando la ejecución fue un BUY (nunca cierra nada);
    closed_quantity y gross_realized_pnl quedan en 0 en ese caso.
    """

    position: Position
    trade: Optional[Trade]
    closed_quantity: Decimal
    gross_realized_pnl: Decimal
