"""
ReconciliationEngine -- detección pura de inconsistencias de estado (Etapa 6.8).

Motor puro, mismo perfil que fill_engine.py/position_engine.py/
risk_engine.py/pnl_engine.py/reservation_engine.py: recibe colecciones y
modelos ya cargados (nunca abre sqlite3, nunca conoce
PaperTradingRepository/PaperTradingService/PaperTradingApplication/
Dashboard), no usa logging ni datetime.now()/uuid.uuid4() (el
`timestamp` de cada hallazgo es siempre el mismo `timestamp` recibido
como argumento). NUNCA escribe ni repara nada -- solo produce un
`ReconciliationReport` de solo lectura (Paso 8).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §22 para el diseño completo y la
justificación de cada código/severidad. Resumen de las reglas
implementadas, por categoría (Pasos 9-14):

- BUY/SELL PENDING: reserva poblada, coherente con quantity/reserved_price.
- Agregación: CashBalance.reserved_balance / Position.reserved_quantity
  vs. la suma exacta de las Órdenes PENDING vigentes.
- Órdenes terminales: solo REJECTED con datos de reserva poblados es un
  hallazgo (FILLED/CANCELLED conservan sus campos históricos por diseño,
  ver §21.2; que no sigan "contribuyendo" al agregado ya lo garantiza la
  agregación, que solo suma PENDING).
- Executions: huérfanas, asociadas a una orden no-FILLED, o
  inconsistentes con filled_quantity/average_fill_price de su Order.
- Trades: exit_execution_id roto, o una SELL FILLED sin ningún Trade.
- PnL: Position.realized_pnl_to_date vs. SUM(Trade.net_pnl) (nunca se
  recalcula aquí, solo se reporta la diferencia).
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.enums import OrderSide, OrderStatus, PositionSide
from src.paper_trading.models import CashBalance, Execution, Order, Position, Trade
from src.paper_trading.reconciliation_models import (
    REPAIRABLE_CODES, IssueCode, ReconciliationIssue, ReconciliationReport, severity_for,
)

ZERO = Decimal("0")


def _make_issue(
    code: IssueCode,
    entity_type: str,
    entity_id: str,
    exchange: Optional[str],
    symbol: Optional[str],
    description: str,
    expected_value: Optional[Decimal],
    actual_value: Optional[Decimal],
    suggested_action: str,
    timestamp: datetime,
) -> ReconciliationIssue:
    """Construye un ReconciliationIssue con severidad/reparabilidad derivadas
    del propio código (§22.3/§22.7) -- nunca se pasan sueltas, para que no
    puedan quedar inconsistentes con la tabla central."""
    return ReconciliationIssue(
        code=code, severity=severity_for(code), entity_type=entity_type, entity_id=entity_id,
        exchange=exchange, symbol=symbol, description=description,
        expected_value=expected_value, actual_value=actual_value,
        repairable=code in REPAIRABLE_CODES, suggested_action=suggested_action, detected_at=timestamp,
    )


class ReconciliationEngine:
    """Analiza el estado persistido de Paper Trading y produce un reporte de
    inconsistencias. Nunca escribe, nunca repara, nunca consulta precios."""

    @staticmethod
    def analyze(
        orders: list[Order],
        executions: list[Execution],
        trades: list[Trade],
        positions: list[Position],
        cash_balances: list[CashBalance],
        timestamp: datetime,
    ) -> ReconciliationReport:
        orders_by_id = {order.id: order for order in orders}
        executions_by_order: dict[str, list[Execution]] = defaultdict(list)
        for execution in executions:
            executions_by_order[execution.order_id].append(execution)

        pending_buy_orders = [
            order for order in orders if order.status == OrderStatus.PENDING and order.side == OrderSide.BUY
        ]
        pending_sell_orders = [
            order for order in orders if order.status == OrderStatus.PENDING and order.side == OrderSide.SELL
        ]

        issues: list[ReconciliationIssue] = []
        issues += _analyze_pending_buy_orders(pending_buy_orders, timestamp)
        issues += _analyze_pending_sell_orders(pending_sell_orders, positions, timestamp)
        issues += _analyze_cash_aggregate(pending_buy_orders, cash_balances, timestamp)
        issues += _analyze_quantity_aggregate(pending_sell_orders, positions, timestamp)
        issues += _analyze_terminal_orders(orders, timestamp)
        issues += _analyze_filled_orders(orders, executions_by_order, timestamp)
        issues += _analyze_executions(orders_by_id, executions, timestamp)
        issues += _analyze_trades(orders_by_id, executions, trades, timestamp)
        issues += _analyze_sell_filled_without_trade(orders, executions_by_order, trades, timestamp)
        issues += _analyze_pnl_consistency(positions, trades, timestamp)
        issues += _analyze_negative_values(cash_balances, positions, timestamp)

        if not issues and _no_activity(orders, positions, cash_balances):
            issues.append(_no_activity_issue(timestamp))

        # Orden determinista (Paso 30), independiente del orden de iteración
        # de los dicts/defaultdicts internos.
        issues.sort(key=lambda issue: (issue.code.value, issue.entity_type, issue.entity_id))

        return ReconciliationReport(generated_at=timestamp, issues=tuple(issues))


def _analyze_pending_buy_orders(pending_buy_orders: list[Order], timestamp: datetime) -> list[ReconciliationIssue]:
    """Paso 9. No valida reserved_fee contra fee_rate (no se persiste por
    orden, ver §22.5/§22.13): solo valida los campos verificables."""
    issues: list[ReconciliationIssue] = []
    for order in pending_buy_orders:
        fields = (order.reserved_price, order.reserved_notional, order.reserved_fee)
        if all(value is None for value in fields):
            issues.append(_make_issue(
                IssueCode.PENDING_BUY_MISSING_RESERVATION, "Order", order.id, order.exchange, order.symbol,
                "Orden BUY PENDING sin ningún campo de reserva poblado "
                "(reserved_price/reserved_notional/reserved_fee).",
                None, None, "Investigar manualmente por qué accept_market_order no reservó recursos.", timestamp,
            ))
            continue
        if any(value is None for value in fields):
            issues.append(_make_issue(
                IssueCode.PENDING_ORDER_INVALID_RESERVED_PRICE, "Order", order.id, order.exchange, order.symbol,
                "Orden BUY PENDING con datos de reserva parcialmente poblados "
                f"(reserved_price={order.reserved_price}, reserved_notional={order.reserved_notional}, "
                f"reserved_fee={order.reserved_fee}).",
                None, None, "Requiere intervención manual: la reserva quedó en un estado parcial imposible.", timestamp,
            ))
            continue

        expected_notional = order.quantity * order.reserved_price
        if order.reserved_notional != expected_notional:
            issues.append(_make_issue(
                IssueCode.PENDING_BUY_RESERVED_CASH_MISMATCH, "Order", order.id, order.exchange, order.symbol,
                f"reserved_notional ({order.reserved_notional}) no coincide con quantity * reserved_price "
                f"({expected_notional}).",
                expected_notional, order.reserved_notional,
                "Requiere intervención manual: no se recalcula automáticamente un campo de Order.", timestamp,
            ))

        if order.reserved_quantity is not None:
            issues.append(_make_issue(
                IssueCode.ORDER_RESERVATION_SIDE_MISMATCH, "Order", order.id, order.exchange, order.symbol,
                "Orden BUY con reserved_quantity poblado; ese campo no aplica al lado BUY (ver §21.2).",
                None, None, "Estado estructuralmente imposible vía Order Pydantic; investigar el origen del dato.",
                timestamp,
            ))
    return issues


def _analyze_pending_sell_orders(
    pending_sell_orders: list[Order], positions: list[Position], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 10."""
    positions_by_key = {(position.exchange, position.symbol): position for position in positions}
    issues: list[ReconciliationIssue] = []
    for order in pending_sell_orders:
        fields = (order.reserved_price, order.reserved_quantity)
        if all(value is None for value in fields):
            issues.append(_make_issue(
                IssueCode.PENDING_SELL_MISSING_RESERVATION, "Order", order.id, order.exchange, order.symbol,
                "Orden SELL PENDING sin ningún campo de reserva poblado (reserved_price/reserved_quantity).",
                None, None, "Investigar manualmente por qué accept_market_order no reservó recursos.", timestamp,
            ))
            continue
        if any(value is None for value in fields):
            issues.append(_make_issue(
                IssueCode.PENDING_ORDER_INVALID_RESERVED_PRICE, "Order", order.id, order.exchange, order.symbol,
                "Orden SELL PENDING con datos de reserva parcialmente poblados "
                f"(reserved_price={order.reserved_price}, reserved_quantity={order.reserved_quantity}).",
                None, None, "Requiere intervención manual: la reserva quedó en un estado parcial imposible.", timestamp,
            ))
            continue

        if order.reserved_quantity != order.quantity:
            issues.append(_make_issue(
                IssueCode.PENDING_SELL_RESERVED_QUANTITY_MISMATCH, "Order", order.id, order.exchange, order.symbol,
                f"reserved_quantity ({order.reserved_quantity}) no coincide con order.quantity ({order.quantity}).",
                order.quantity, order.reserved_quantity,
                "Requiere intervención manual: no se recalcula automáticamente un campo de Order.", timestamp,
            ))

        position = positions_by_key.get((order.exchange, order.symbol))
        if position is None or position.side != PositionSide.LONG:
            issues.append(_make_issue(
                IssueCode.PENDING_SELL_RESERVED_QUANTITY_MISMATCH, "Order", order.id, order.exchange, order.symbol,
                "No existe una Position LONG correspondiente para esta reserva SELL PENDING.",
                None, None, "Requiere intervención manual: revisar la Position asociada.", timestamp,
            ))

        if order.reserved_notional is not None or order.reserved_fee is not None:
            issues.append(_make_issue(
                IssueCode.ORDER_RESERVATION_SIDE_MISMATCH, "Order", order.id, order.exchange, order.symbol,
                "Orden SELL con reserved_notional/reserved_fee poblado; esos campos no aplican al lado SELL "
                "(ver §21.2).",
                None, None, "Estado estructuralmente imposible vía Order Pydantic; investigar el origen del dato.",
                timestamp,
            ))
    return issues


def _analyze_cash_aggregate(
    pending_buy_orders: list[Order], cash_balances: list[CashBalance], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 11 (BUY). El dominio actual opera una única cuenta/moneda (ver
    §22.5): se suma sobre TODAS las BUY PENDING, sin distinguir moneda
    (Order no tiene un campo currency), y se compara contra cada
    CashBalance recibido -- válido para el caso real de una única
    moneda activa."""
    expected = ZERO
    for order in pending_buy_orders:
        if order.reserved_notional is not None and order.reserved_fee is not None:
            expected += order.reserved_notional + order.reserved_fee

    issues: list[ReconciliationIssue] = []
    for cash_balance in cash_balances:
        actual = cash_balance.reserved_balance
        if actual == expected:
            continue
        if expected == ZERO and actual != ZERO:
            issues.append(_make_issue(
                IssueCode.ORPHAN_CASH_RESERVATION, "CashBalance", cash_balance.currency, None, None,
                f"reserved_balance ({actual}) > 0 pero no hay ninguna orden BUY PENDING vigente que lo justifique.",
                expected, actual,
                "repair() puede recalcular reserved_balance como la suma exacta de las BUY PENDING vigentes.",
                timestamp,
            ))
        else:
            issues.append(_make_issue(
                IssueCode.CASH_RESERVED_BALANCE_MISMATCH, "CashBalance", cash_balance.currency, None, None,
                f"reserved_balance ({actual}) no coincide con la suma esperada de reservas BUY PENDING ({expected}).",
                expected, actual,
                "repair() puede recalcular reserved_balance como la suma exacta de las BUY PENDING vigentes.",
                timestamp,
            ))
    return issues


def _analyze_quantity_aggregate(
    pending_sell_orders: list[Order], positions: list[Position], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 11 (SELL), por (exchange, symbol)."""
    expected_by_key: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for order in pending_sell_orders:
        if order.reserved_quantity is not None:
            expected_by_key[(order.exchange, order.symbol)] += order.reserved_quantity

    positions_by_key = {(position.exchange, position.symbol): position for position in positions}
    all_keys = set(expected_by_key) | set(positions_by_key)

    issues: list[ReconciliationIssue] = []
    for exchange, symbol in sorted(all_keys):
        expected = expected_by_key.get((exchange, symbol), ZERO)
        position = positions_by_key.get((exchange, symbol))
        actual = position.reserved_quantity if position is not None else ZERO
        if actual == expected:
            continue
        entity_id = f"{exchange}:{symbol}"
        if expected == ZERO and actual != ZERO:
            issues.append(_make_issue(
                IssueCode.ORPHAN_POSITION_RESERVATION, "Position", entity_id, exchange, symbol,
                f"reserved_quantity ({actual}) > 0 pero no hay ninguna orden SELL PENDING vigente que lo justifique.",
                expected, actual,
                "repair() puede recalcular reserved_quantity como la suma exacta de las SELL PENDING vigentes.",
                timestamp,
            ))
        else:
            issues.append(_make_issue(
                IssueCode.POSITION_RESERVED_QUANTITY_MISMATCH, "Position", entity_id, exchange, symbol,
                f"reserved_quantity ({actual}) no coincide con la suma esperada de reservas SELL PENDING ({expected}).",
                expected, actual,
                "repair() puede recalcular reserved_quantity como la suma exacta de las SELL PENDING vigentes.",
                timestamp,
            ))
    return issues


def _analyze_terminal_orders(orders: list[Order], timestamp: datetime) -> list[ReconciliationIssue]:
    """Paso 12. Solo REJECTED con datos de reserva poblados es un hallazgo
    (FILLED/CANCELLED conservan sus campos históricos por diseño, §21.2;
    ver §22.5 para la justificación completa)."""
    issues: list[ReconciliationIssue] = []
    for order in orders:
        if order.status != OrderStatus.REJECTED:
            continue
        fields = (order.reserved_price, order.reserved_notional, order.reserved_fee, order.reserved_quantity)
        if any(value is not None for value in fields):
            issues.append(_make_issue(
                IssueCode.TERMINAL_ORDER_HAS_RESERVATION, "Order", order.id, order.exchange, order.symbol,
                "Orden REJECTED con campos de reserva poblados; un rechazo de riesgo nunca llega a "
                "ReservationEngine (ver accept_market_order).",
                None, None, "Requiere intervención manual: revisar el flujo que aceptó/rechazó esta orden.", timestamp,
            ))
    return issues


def _analyze_filled_orders(
    orders: list[Order], executions_by_order: dict[str, list[Execution]], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 12 (FILLED) + Paso 13 (coherencia con su Execution)."""
    issues: list[ReconciliationIssue] = []
    for order in orders:
        if order.status != OrderStatus.FILLED:
            continue
        order_executions = executions_by_order.get(order.id, [])
        if not order_executions:
            issues.append(_make_issue(
                IssueCode.FILLED_ORDER_WITHOUT_EXECUTION, "Order", order.id, order.exchange, order.symbol,
                "Orden FILLED sin ninguna Execution asociada.",
                None, None, "Requiere intervención manual: nunca se crea una Execution automáticamente.", timestamp,
            ))
            continue
        if len(order_executions) > 1:
            issues.append(_make_issue(
                IssueCode.MULTIPLE_EXECUTIONS_FOR_FULL_FILL_ORDER, "Order", order.id, order.exchange, order.symbol,
                f"Orden FILLED (full-fill MARKET) con {len(order_executions)} Executions; se esperaba exactamente 1.",
                None, None, "Revisar manualmente si corresponde a un escenario fuera del alcance actual (solo full-fill).",
                timestamp,
            ))
            continue
        execution = order_executions[0]
        if execution.quantity != order.filled_quantity or execution.price != order.average_fill_price:
            issues.append(_make_issue(
                IssueCode.FILLED_ORDER_EXECUTION_MISMATCH, "Order", order.id, order.exchange, order.symbol,
                f"filled_quantity/average_fill_price ({order.filled_quantity}/{order.average_fill_price}) no "
                f"coincide con su Execution ({execution.quantity}/{execution.price}).",
                None, None, "Requiere intervención manual: no se recalcula automáticamente un campo de Order.",
                timestamp,
            ))
    return issues


def _analyze_executions(
    orders_by_id: dict[str, Order], executions: list[Execution], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 13: Executions huérfanas o asociadas a una orden incompatible."""
    issues: list[ReconciliationIssue] = []
    for execution in executions:
        order = orders_by_id.get(execution.order_id)
        if order is None:
            issues.append(_make_issue(
                IssueCode.ORPHAN_EXECUTION, "Execution", execution.id, execution.exchange, execution.symbol,
                f"execution.order_id ({execution.order_id}) no corresponde a ninguna Order existente.",
                None, None, "Investigar manualmente el origen de esta Execution huérfana.", timestamp,
            ))
            continue
        if order.exchange != execution.exchange or order.symbol != execution.symbol:
            issues.append(_make_issue(
                IssueCode.ORPHAN_EXECUTION, "Execution", execution.id, execution.exchange, execution.symbol,
                f"execution.exchange/symbol no coincide con la Order {order.id} "
                f"({order.exchange}:{order.symbol}).",
                None, None, "Investigar manualmente el origen de esta Execution huérfana.", timestamp,
            ))
            continue
        if order.status != OrderStatus.FILLED:
            issues.append(_make_issue(
                IssueCode.EXECUTION_FOR_NON_FILLED_ORDER, "Execution", execution.id, execution.exchange,
                execution.symbol,
                f"Existe una Execution para la orden {order.id}, cuyo status es {order.status.value} (no FILLED).",
                None, None, "Requiere intervención manual: revisar por qué existe esta Execution.", timestamp,
            ))
    return issues


def _analyze_trades(
    orders_by_id: dict[str, Order], executions: list[Execution], trades: list[Trade], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 13: exit_execution_id roto o incoherente."""
    executions_by_id = {execution.id: execution for execution in executions}
    issues: list[ReconciliationIssue] = []
    for trade in trades:
        execution = executions_by_id.get(trade.exit_execution_id)
        if execution is None:
            issues.append(_make_issue(
                IssueCode.TRADE_WITHOUT_EXIT_EXECUTION, "Trade", trade.id, trade.exchange, trade.symbol,
                f"trade.exit_execution_id ({trade.exit_execution_id}) no corresponde a ninguna Execution existente.",
                None, None, "Investigar manualmente el origen de este Trade.", timestamp,
            ))
            continue
        order = orders_by_id.get(execution.order_id)
        if (
            order is None or order.side != OrderSide.SELL or order.status != OrderStatus.FILLED
            or order.exchange != trade.exchange or order.symbol != trade.symbol
        ):
            issues.append(_make_issue(
                IssueCode.TRADE_WITHOUT_EXIT_EXECUTION, "Trade", trade.id, trade.exchange, trade.symbol,
                "La Execution referenciada por exit_execution_id no corresponde a una orden SELL FILLED "
                "coherente con este Trade.",
                None, None, "Investigar manualmente el origen de este Trade.", timestamp,
            ))
    return issues


def _analyze_sell_filled_without_trade(
    orders: list[Order],
    executions_by_order: dict[str, list[Execution]],
    trades: list[Trade],
    timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 13: una SELL FILLED sin ningún Trade -- nunca se crea uno."""
    execution_ids_with_trade = {trade.exit_execution_id for trade in trades}
    issues: list[ReconciliationIssue] = []
    for order in orders:
        if order.status != OrderStatus.FILLED or order.side != OrderSide.SELL:
            continue
        order_execution_ids = {execution.id for execution in executions_by_order.get(order.id, [])}
        if not (order_execution_ids & execution_ids_with_trade):
            issues.append(_make_issue(
                IssueCode.SELL_FILLED_WITHOUT_TRADE, "Order", order.id, order.exchange, order.symbol,
                "Orden SELL FILLED sin ningún Trade cuyo exit_execution_id apunte a alguna de sus Executions.",
                None, None,
                "Requiere intervención manual: nunca se crea un Trade automáticamente (reconstruir el contexto "
                "histórico completo está fuera de alcance).",
                timestamp,
            ))
    return issues


def _analyze_pnl_consistency(
    positions: list[Position], trades: list[Trade], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Paso 14. Nunca recalcula Position.realized_pnl_to_date, solo reporta
    la diferencia (misma regla que check_position_pnl_consistency, Etapa 6.3,
    reimplementada aquí porque el motor no puede llamar al repositorio)."""
    realized_by_key: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for trade in trades:
        realized_by_key[(trade.exchange, trade.symbol)] += trade.net_pnl

    issues: list[ReconciliationIssue] = []
    for position in positions:
        key = (position.exchange, position.symbol)
        expected = realized_by_key.get(key, ZERO)
        if position.realized_pnl_to_date != expected:
            issues.append(_make_issue(
                IssueCode.POSITION_PNL_INCONSISTENT, "Position", f"{key[0]}:{key[1]}", key[0], key[1],
                f"realized_pnl_to_date ({position.realized_pnl_to_date}) no coincide con SUM(Trade.net_pnl) "
                f"({expected}).",
                expected, position.realized_pnl_to_date,
                "No se recalcula automáticamente en esta etapa; requiere revisión manual del historial de Trades.",
                timestamp,
            ))
    return issues


def _analyze_negative_values(
    cash_balances: list[CashBalance], positions: list[Position], timestamp: datetime,
) -> list[ReconciliationIssue]:
    """Comprobación defensiva (§22.5): estructuralmente inalcanzable a través
    de CashBalance/Position válidos (sus propios invariantes Pydantic ya
    impiden reserved > total/quantity), pero se conserva por si el motor
    recibe modelos construidos con model_construct() desde fuera del
    repositorio real."""
    issues: list[ReconciliationIssue] = []
    for cash_balance in cash_balances:
        if cash_balance.available_balance < ZERO:
            issues.append(_make_issue(
                IssueCode.NEGATIVE_AVAILABLE_CASH, "CashBalance", cash_balance.currency, None, None,
                f"available_balance ({cash_balance.available_balance}) es negativo.",
                ZERO, cash_balance.available_balance,
                "Corrupción estructuralmente imposible bajo los invariantes de CashBalance; investigar el origen.",
                timestamp,
            ))
    for position in positions:
        if position.available_quantity < ZERO:
            issues.append(_make_issue(
                IssueCode.NEGATIVE_AVAILABLE_QUANTITY, "Position", f"{position.exchange}:{position.symbol}",
                position.exchange, position.symbol,
                f"available_quantity ({position.available_quantity}) es negativo.",
                ZERO, position.available_quantity,
                "Corrupción estructuralmente imposible bajo los invariantes de Position; investigar el origen.",
                timestamp,
            ))
    return issues


def _no_activity(orders: list[Order], positions: list[Position], cash_balances: list[CashBalance]) -> bool:
    """Paso 7 (INFO): "ausencia total de operaciones" (ver §22.4)."""
    if orders:
        return False
    if any(position.side != PositionSide.FLAT for position in positions):
        return False
    if any(cash_balance.reserved_balance != ZERO for cash_balance in cash_balances):
        return False
    return True


def _no_activity_issue(timestamp: datetime) -> ReconciliationIssue:
    return _make_issue(
        IssueCode.NO_ACTIVITY, "System", "-", None, None,
        "No existe ninguna Order, ninguna Position no-FLAT ni ningún saldo reservado en el sistema.",
        None, None, "Ninguna acción requerida.", timestamp,
    )
