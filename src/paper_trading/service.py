"""
PaperTradingService -- orquestación transaccional de Paper Trading (Etapa 6.4).

Única capa autorizada para ejecutar una orden de Paper Trading de punta
a punta: valida riesgo (RiskEngine), simula el llenado (FillEngine),
aplica el resultado sobre la posición (PositionEngine), actualiza el
efectivo, calcula snapshots (PnLEngine) y persiste todo en una única
transacción (PaperTradingRepository.save_fill_transaction). No
implementa ninguna regla de negocio propia: cada cálculo de dominio
(fees, PnL, promedio ponderado, límites de riesgo) ya vive en su motor
correspondiente (Etapa 6.2); este servicio solo los invoca en el orden
correcto y decide qué persistir.

Alcance de esta iteración (ver docs/ARQUITECTURA_PAPER_TRADING.md):
- Solo OrderType.MARKET, solo PositionSide.LONG/FLAT (mismo alcance que
  los motores; ver fill_engine.py/position_engine.py).
- `submit_market_order()` es un flujo de "validar y llenar" en una sola
  llamada: la orden pasa de NEW a PENDING (solo en memoria, para
  satisfacer la precondición de FillEngine) y de ahí directo a FILLED
  dentro de la misma llamada -- no queda un estado PENDING persistido
  por separado, y no se reserva capital/cantidad
  (`CashBalance.reserved_balance`/`Position.reserved_quantity`
  permanecen sin usar, igual que en las Etapas 6.2/6.3). El ciclo de
  vida completo de reserva-al-aceptar/libera-al-llenar descrito en
  ARQUITECTURA_PAPER_TRADING.md §9 queda para una iteración futura que
  separe "aceptar" de "llenar" en dos llamadas distintas.
- El snapshot de cartera (`PortfolioSnapshot`) requiere un precio por
  cada posición abierta no-FLAT (ver `PnLEngine.build_portfolio_snapshot`);
  este servicio solo conoce con certeza el precio del símbolo operado
  (`market_price`). Si la cuenta tiene otras posiciones abiertas en
  otros símbolos, el llamador debe proveerlos en `current_prices`; si
  falta alguno, `PnLEngine` falla explícitamente (nunca se inventa un
  precio, ver §9 de la Etapa 6.2).
- Si todavía no existe un `CashBalance` para la moneda solicitada (la
  cuenta nunca se sembró con capital inicial -- eso llega con
  `config.yaml`/Composition Root en una etapa futura, ver §9.2), este
  servicio falla explícitamente con `ValueError` en vez de inventar un
  saldo.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.enums import OrderSide, OrderStatus, PositionSide
from src.paper_trading.fill_engine import FillEngine
from src.paper_trading.models import CashBalance, Order, Position
from src.paper_trading.pnl_engine import PnLEngine
from src.paper_trading.position_engine import PositionEngine
from src.paper_trading.risk_engine import RiskEngine
from src.paper_trading.service_results import SubmitOrderResult

ZERO = Decimal("0")


class PaperTradingService:
    """Coordina RiskEngine + FillEngine + PositionEngine + PnLEngine + PaperTradingRepository."""

    def __init__(
        self,
        repository: PaperTradingRepository,
        fill_engine=FillEngine,
        position_engine=PositionEngine,
        pnl_engine=PnLEngine,
        risk_engine=RiskEngine,
    ):
        self._repository = repository
        self._fill_engine = fill_engine
        self._position_engine = position_engine
        self._pnl_engine = pnl_engine
        self._risk_engine = risk_engine

    def submit_market_order(
        self,
        order: Order,
        market_price: Decimal,
        fee_rate: Decimal,
        timestamp: datetime,
        execution_id: str,
        max_order_value: Decimal,
        max_position_value: Decimal,
        rules_version: str,
        trade_id: Optional[str] = None,
        currency: str = "USDT",
        current_prices: Optional[dict[tuple[str, str], Decimal]] = None,
    ) -> SubmitOrderResult:
        """Valida y llena una orden MARKET de punta a punta.

        No muta ningún argumento recibido. Si RiskEngine rechaza la
        orden, devuelve `SubmitOrderResult(success=False, ...)` sin
        ejecutar ni persistir nada (un rechazo de riesgo es un
        resultado normal, no una excepción). Cualquier excepción que sí
        se propague representa un dato estructuralmente imposible o un
        error de programación (ver risk_engine.py/fill_engine.py/
        position_engine.py).
        """
        # 1. leer estado actual
        position = self._repository.get_position(order.exchange, order.symbol)
        if position is None:
            position = Position(
                exchange=order.exchange, symbol=order.symbol, side=PositionSide.FLAT,
                quantity=ZERO, updated_at=timestamp,
            )

        cash_balance = self._repository.get_cash_balance(currency)
        if cash_balance is None:
            raise ValueError(
                f"No existe CashBalance para la moneda '{currency}'. Debe sembrarse el "
                "capital inicial antes de poder operar (ver ARQUITECTURA_PAPER_TRADING.md §9.2)."
            )

        # 2. validar riesgo
        risk_result = self._risk_engine.validate_order(
            order=order,
            cash_balance=cash_balance,
            position=position,
            market_price=market_price,
            max_order_value=max_order_value,
            max_position_value=max_position_value,
            fee_rate=fee_rate,
            timestamp=timestamp,
            rules_version=rules_version,
        )
        if not risk_result.approved:
            return SubmitOrderResult(
                success=False, risk_result=risk_result, order=order, execution=None,
                position=None, trade=None, cash_balance=None, portfolio_snapshot=None, pnl_snapshot=None,
            )

        # 3. FillEngine (requiere PENDING/PARTIALLY_FILLED; la orden llega NEW)
        pending_order = Order(**{**order.model_dump(), "status": OrderStatus.PENDING, "updated_at": timestamp})
        fill_result = self._fill_engine.execute_market_order(
            order=pending_order, market_price=market_price, fee_rate=fee_rate,
            executed_at=timestamp, execution_id=execution_id,
        )

        # 4. PositionEngine
        position_result = self._position_engine.apply_execution(
            position=position, order=fill_result.order, execution=fill_result.execution,
            updated_at=timestamp, trade_id=trade_id,
        )

        # 5. actualizar CashBalance
        notional = fill_result.execution.quantity * fill_result.execution.price
        if order.side == OrderSide.BUY:
            new_total_balance = cash_balance.total_balance - notional - fill_result.execution.fee
        else:
            new_total_balance = cash_balance.total_balance + notional - fill_result.execution.fee

        new_cash_balance = CashBalance(
            currency=cash_balance.currency,
            total_balance=new_total_balance,
            reserved_balance=cash_balance.reserved_balance,
            updated_at=timestamp,
        )

        # 6. snapshots (PnLEngine)
        symbol_key = (order.exchange, order.symbol)
        prices = {symbol_key: market_price}
        if current_prices:
            prices.update(current_prices)

        other_positions = [
            existing for existing in self._repository.fetch_positions()
            if (existing.exchange, existing.symbol) != symbol_key
        ]
        all_positions = other_positions + [position_result.position]

        portfolio_snapshot = self._pnl_engine.build_portfolio_snapshot(
            cash_balance=new_cash_balance, positions=all_positions, current_prices=prices, timestamp=timestamp,
        )
        pnl_snapshot = self._pnl_engine.build_pnl_snapshot(
            position=position_result.position, current_price=market_price, timestamp=timestamp,
        )

        # 7. persistir todo en una única transacción
        self._repository.save_fill_transaction(
            order=fill_result.order,
            execution=fill_result.execution,
            position=position_result.position,
            cash_balance=new_cash_balance,
            trade=position_result.trade,
            portfolio_snapshot=portfolio_snapshot,
            pnl_snapshot=pnl_snapshot,
        )

        # 8. resultado completo
        return SubmitOrderResult(
            success=True,
            risk_result=risk_result,
            order=fill_result.order,
            execution=fill_result.execution,
            position=position_result.position,
            trade=position_result.trade,
            cash_balance=new_cash_balance,
            portfolio_snapshot=portfolio_snapshot,
            pnl_snapshot=pnl_snapshot,
        )
