"""
Tipo de resultado devuelto por PaperTradingService (Etapa 6.4).

Se centraliza en un archivo propio, separado de service.py, por el
mismo motivo que results.py ya separa FillResult/PositionUpdateResult
de los motores: es un tipo de dato de retorno, no lógica de
orquestación, y evita que service.py se recargue con la definición.

NamedTuple, no BaseModel: no es una entidad de dominio que se persista
ni se valide (eso ya lo hicieron Order/Execution/Position/Trade/
CashBalance/PortfolioSnapshot/PnLSnapshot al construirse) -- es solo el
resultado, inmutable, de una llamada a
PaperTradingService.submit_market_order().
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
