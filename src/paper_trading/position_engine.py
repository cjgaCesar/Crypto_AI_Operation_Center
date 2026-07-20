"""
PositionEngine -- aplica una Execution ya ocurrida sobre una Position (Etapa 6.2).

Motor puro (ver docs/ARQUITECTURA_PAPER_TRADING.md §6): implementa las
reglas de abrir/aumentar una posición LONG (BUY) y reducir/cerrar una
posición LONG (SELL). No procesa SHORT ni reversión LONG->SHORT en este
MVP (diferido, ver §5.1).

Tratamiento de comisiones (ver ARQUITECTURA_PAPER_TRADING.md §6.2):
Trade.fees es, en este MVP, exactamente execution.fee de la ejecución
que cierra (SELL). La comisión de la ejecución que abrió la posición
(BUY) ya se dedujo de CashBalance en su momento -- fuera del alcance de
este motor, que no conoce CashBalance -- y NO se reasigna
retroactivamente al Trade. Esta es una limitación conocida y
documentada, no un olvido: reasignarla exigiría rastrear qué
ejecuciones de apertura específicas componen la porción cerrada, algo
incompatible con el costeo por promedio ponderado ya elegido para
Position (ver ARQUITECTURA_PAPER_TRADING.md §2.3).

Nota sobre `Position.realized_pnl_to_date`: este motor lo actualiza de
forma incremental (`+ net_pnl`) porque en esta iteración no existe
ningún repositorio del cual recalcularlo vía SUM(Trade.net_pnl) (ver
§12.2 -- llegará en la Etapa 6.3). Usar Decimal (no float) hace que esta
suma incremental sea aritméticamente exacta, sin el riesgo de deriva
por redondeo que la auditoría 6.0.1 había señalado para float; cuando
exista un repositorio, recalcular desde la fuente sigue siendo preferible
y no depende de que esta función cambie.

Interfaz: se agregó el parámetro `trade_id` (ausente en la interfaz
sugerida del enunciado) porque `Trade.id` es un campo obligatorio que
este motor no puede generar internamente sin violar la regla de pureza
"los IDs se reciben como argumento, nunca uuid.uuid4() interno" (Paso 8
de la Etapa 6.2). Es `Optional[str] = None` porque solo es obligatorio
cuando la ejecución efectivamente cierra parte de una posición (SELL);
un BUY nunca lo necesita.

Convención de excepciones de este módulo (no se modifica exceptions.py):
- OverFillError: una SELL supera Position.available_quantity.
- PaperTradingDomainError (clase base, no una subclase más específica):
  cualquier intento de operar sobre una posición SHORT, o una SELL
  sobre una posición FLAT -- ninguno de los dos encaja semánticamente
  en "transición de Order inválida" ni en "exceso de cantidad", por eso
  se usa la excepción base del dominio en vez de forzar una de las dos
  subclases existentes a significar algo que no describen.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.enums import OrderSide, PositionSide, TradeSide
from src.paper_trading.exceptions import OverFillError, PaperTradingDomainError
from src.paper_trading.models import Execution, Order, Position, Trade
from src.paper_trading.results import PositionUpdateResult

ZERO = Decimal("0")


class PositionEngine:
    """Aplica una Execution (ya ocurrida) sobre una Position, produciendo el nuevo estado."""

    @staticmethod
    def apply_execution(
        position: Position,
        order: Order,
        execution: Execution,
        updated_at: datetime,
        trade_id: Optional[str] = None,
    ) -> PositionUpdateResult:
        if position.side == PositionSide.SHORT:
            raise PaperTradingDomainError(
                "PositionEngine no soporta posiciones SHORT en esta iteración (ver §5.1)."
            )

        if order.side == OrderSide.BUY:
            return PositionEngine._apply_buy(position, execution, updated_at)

        return PositionEngine._apply_sell(position, execution, updated_at, trade_id)

    @staticmethod
    def _apply_buy(position: Position, execution: Execution, updated_at: datetime) -> PositionUpdateResult:
        if position.side == PositionSide.FLAT:
            new_quantity = execution.quantity
            new_average_entry_price = execution.price
            new_opened_at = execution.executed_at
        else:  # LONG: aumenta la posición existente (promedio ponderado, §6.1)
            new_quantity = position.quantity + execution.quantity
            new_average_entry_price = (
                (position.quantity * position.average_entry_price) + (execution.quantity * execution.price)
            ) / new_quantity
            new_opened_at = position.opened_at

        updated_fields = position.model_dump()
        updated_fields.update(
            side=PositionSide.LONG,
            quantity=new_quantity,
            average_entry_price=new_average_entry_price,
            opened_at=new_opened_at,
            updated_at=updated_at,
        )
        new_position = Position(**updated_fields)

        return PositionUpdateResult(
            position=new_position, trade=None, closed_quantity=ZERO, gross_realized_pnl=ZERO,
        )

    @staticmethod
    def _apply_sell(
        position: Position, execution: Execution, updated_at: datetime, trade_id: Optional[str],
    ) -> PositionUpdateResult:
        if position.side == PositionSide.FLAT:
            raise PaperTradingDomainError("No se puede vender: la posición está FLAT.")

        if execution.quantity > position.available_quantity:
            raise OverFillError(
                f"execution.quantity ({execution.quantity}) supera "
                f"available_quantity ({position.available_quantity})."
            )

        if trade_id is None:
            raise ValueError(
                "trade_id es obligatorio: una SELL sobre una posición LONG siempre genera un Trade."
            )

        gross_realized_pnl = (execution.price - position.average_entry_price) * execution.quantity
        fees = execution.fee
        net_pnl = gross_realized_pnl - fees

        remaining_quantity = position.quantity - execution.quantity
        if remaining_quantity > ZERO:
            new_side = PositionSide.LONG
            new_average_entry_price = position.average_entry_price
            new_opened_at = position.opened_at
        else:
            new_side = PositionSide.FLAT
            new_average_entry_price = None
            new_opened_at = None

        trade = Trade(
            id=trade_id,
            exchange=position.exchange,
            symbol=position.symbol,
            side=TradeSide.LONG,
            quantity=execution.quantity,
            entry_price=position.average_entry_price,
            exit_price=execution.price,
            gross_pnl=gross_realized_pnl,
            fees=fees,
            net_pnl=net_pnl,
            opened_at=position.opened_at,
            closed_at=execution.executed_at,
            exit_execution_id=execution.id,
        )

        updated_fields = position.model_dump()
        updated_fields.update(
            side=new_side,
            quantity=remaining_quantity,
            average_entry_price=new_average_entry_price,
            opened_at=new_opened_at,
            realized_pnl_to_date=position.realized_pnl_to_date + net_pnl,
            updated_at=updated_at,
        )
        new_position = Position(**updated_fields)

        return PositionUpdateResult(
            position=new_position,
            trade=trade,
            closed_quantity=execution.quantity,
            gross_realized_pnl=gross_realized_pnl,
        )
