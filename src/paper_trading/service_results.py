"""
Tipos de resultado devueltos por PaperTradingService (Etapa 6.4,
ampliado en 6.7 con el ciclo explícito aceptar/llenar/cancelar).

Se centralizan en un archivo propio, separado de service.py, por el
mismo motivo que results.py ya separa FillResult/PositionUpdateResult
de los motores: son tipos de dato de retorno, no lógica de
orquestación, y evita que service.py se recargue con la definición.

NamedTuple, no BaseModel: no son entidades de dominio que se persistan
ni se validen (eso ya lo hicieron Order/Execution/Position/Trade/
CashBalance/PortfolioSnapshot/PnLSnapshot al construirse) -- son solo el
resultado, inmutable, de una llamada al Service.
"""

from typing import NamedTuple, Optional

from src.paper_trading.models import (
    CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, RiskValidationResult, Trade,
)


class SubmitOrderResult(NamedTuple):
    """Resultado completo de someter una orden MARKET a PaperTradingService.

    Si `success` es False, la orden fue rechazada por RiskEngine:
    `risk_result.approved` es False y todos los campos posteriores a la
    validación de riesgo (execution/position/trade/cash_balance/
    snapshots) quedan en None -- nada se ejecutó ni se persistió.
    """

    success: bool
    risk_result: RiskValidationResult
    order: Order
    execution: Optional[Execution]
    position: Optional[Position]
    trade: Optional[Trade]
    cash_balance: Optional[CashBalance]
    portfolio_snapshot: Optional[PortfolioSnapshot]
    pnl_snapshot: Optional[PnLSnapshot]


class AcceptOrderResult(NamedTuple):
    """Resultado de PaperTradingService.accept_market_order() (Etapa 6.7).

    Si `success` es False, la orden fue rechazada por RiskEngine antes
    de reservar nada: `cash_balance`/`position` quedan en None y
    `reservation_created` es False. Si `success` es True, `order` está
    en PENDING con sus campos de reserva poblados (ver §21.2) y ya
    persistida atómicamente junto con `cash_balance`/`position`.
    """

    success: bool
    risk_result: RiskValidationResult
    order: Order
    cash_balance: Optional[CashBalance]
    position: Optional[Position]
    reservation_created: bool


class FillPendingOrderResult(NamedTuple):
    """Resultado de PaperTradingService.fill_pending_order() (Etapa 6.7).

    Siempre representa un llenado exitoso: un estado inválido (orden no
    PENDING, reserva ya liberada, etc.) lanza una excepción en vez de
    devolver este resultado con success=False (ver §21.9 -- no es un
    rechazo de riesgo, el riesgo ya se validó al aceptar).
    """

    order: Order
    execution: Execution
    position: Position
    trade: Optional[Trade]
    cash_balance: CashBalance
    portfolio_snapshot: Optional[PortfolioSnapshot]
    pnl_snapshot: Optional[PnLSnapshot]
    reservation_released: bool


class CancelOrderResult(NamedTuple):
    """Resultado de PaperTradingService.cancel_pending_order() (Etapa 6.7).

    Nunca genera Execution ni Trade: cancelar solo libera la reserva
    (ver §21.4) y mueve la orden a CANCELLED, sin liquidar nada.
    """

    order: Order
    cash_balance: CashBalance
    position: Position
    reservation_released: bool
