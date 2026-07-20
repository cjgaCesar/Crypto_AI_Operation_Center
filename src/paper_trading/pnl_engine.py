"""
PnLEngine -- cálculo de PnL no realizado y snapshots agregados (Etapa 6.2).

Motor puro (ver docs/ARQUITECTURA_PAPER_TRADING.md §6, §7, §2.8, §2.9):
solo lee Position/CashBalance y un precio de referencia explícito, sin
modificar ninguno de los dos. Solo soporta LONG/FLAT (SHORT diferido,
§5.1).

Nota (Paso 6 de la Etapa 6.2): bajo el modelo contable actual,
CashBalance.total_balance representa el efectivo total de la cuenta
(no invertido en posiciones abiertas). PortfolioSnapshot.cash_balance
reexpone ese mismo valor sin transformarlo; total_equity es ese
efectivo más el valor de mercado de las posiciones abiertas -- ver
ARQUITECTURA_PAPER_TRADING.md §7 (equivalente a `available_balance +
reserved_balance + positions_value`, porque `total_balance ==
available_balance + reserved_balance` por definición, §2.5).
"""

from datetime import datetime
from decimal import Decimal

from src.paper_trading.enums import PositionSide
from src.paper_trading.exceptions import PaperTradingDomainError
from src.paper_trading.models import CashBalance, PnLSnapshot, Position, PortfolioSnapshot

ZERO = Decimal("0")


class PnLEngine:
    """Cálculo de PnL no realizado, valor de posición y snapshots agregados."""

    @staticmethod
    def calculate_unrealized_pnl(position: Position, current_price: Decimal) -> Decimal:
        """(current_price - average_entry_price) * quantity para LONG; 0 para FLAT."""
        if position.side == PositionSide.SHORT:
            raise PaperTradingDomainError(
                "PnLEngine no soporta posiciones SHORT en esta iteración (ver §5.1)."
            )
        if position.side == PositionSide.FLAT:
            return ZERO
        if current_price <= ZERO:
            raise ValueError("current_price debe ser mayor que 0 para una posición LONG.")
        return (current_price - position.average_entry_price) * position.quantity

    @staticmethod
    def calculate_position_value(position: Position, current_price: Decimal) -> Decimal:
        """current_price * quantity para LONG; 0 para FLAT."""
        if position.side == PositionSide.SHORT:
            raise PaperTradingDomainError(
                "PnLEngine no soporta posiciones SHORT en esta iteración (ver §5.1)."
            )
        if position.side == PositionSide.FLAT:
            return ZERO
        if current_price <= ZERO:
            raise ValueError("current_price debe ser mayor que 0 para una posición LONG.")
        return current_price * position.quantity

    @staticmethod
    def build_pnl_snapshot(position: Position, current_price: Decimal, timestamp: datetime) -> PnLSnapshot:
        """Un PnLSnapshot puntual para `position`, con el PnL no realizado a `current_price`."""
        unrealized_pnl = PnLEngine.calculate_unrealized_pnl(position, current_price)
        return PnLSnapshot(
            timestamp=timestamp,
            exchange=position.exchange,
            symbol=position.symbol,
            position_quantity=position.quantity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_cumulative=position.realized_pnl_to_date,
        )

    @staticmethod
    def build_portfolio_snapshot(
        cash_balance: CashBalance,
        positions: list[Position],
        current_prices: dict[tuple[str, str], Decimal],
        timestamp: datetime,
    ) -> PortfolioSnapshot:
        """Agrega cash_balance + todas las positions en un PortfolioSnapshot.

        `current_prices` debe traer una entrada `(exchange, symbol)` por
        cada posición no-FLAT; si falta alguna, falla explícitamente (no
        se inventa un precio 0). Las posiciones FLAT no requieren precio:
        no aportan valor de mercado ni PnL no realizado, pero sí siguen
        aportando su `realized_pnl_to_date` histórico al acumulado.
        """
        total_positions_value = ZERO
        total_unrealized_pnl = ZERO
        total_realized_pnl = ZERO

        for position in positions:
            total_realized_pnl += position.realized_pnl_to_date
            if position.side == PositionSide.FLAT:
                continue
            key = (position.exchange, position.symbol)
            if key not in current_prices:
                raise ValueError(f"Falta current_price para la posición {key}.")
            price = current_prices[key]
            total_positions_value += PnLEngine.calculate_position_value(position, price)
            total_unrealized_pnl += PnLEngine.calculate_unrealized_pnl(position, price)

        total_equity = cash_balance.total_balance + total_positions_value
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash_balance=cash_balance.total_balance,
            positions_value=total_positions_value,
            total_equity=total_equity,
            unrealized_pnl_total=total_unrealized_pnl,
            realized_pnl_cumulative=total_realized_pnl,
        )
