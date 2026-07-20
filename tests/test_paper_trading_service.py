"""
Pruebas para src/paper_trading/service.py (PaperTradingService), Etapa 6.4.

Usa el repositorio SQLite real (SQLitePaperTradingRepository) con
`tmp_path`, no un Fake: el objetivo de esta etapa es verificar que el
servicio orquesta motores + persistencia correctamente de punta a
punta, incluyendo la atomicidad real de save_fill_transaction.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.exceptions import InvalidOrderStateError
from src.paper_trading.models import CashBalance, Order
from src.paper_trading.service import PaperTradingService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _service(tmp_path, initial_capital=Decimal("10000")) -> tuple[PaperTradingService, SQLitePaperTradingRepository]:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    repo.save_cash_balance(CashBalance(total_balance=initial_capital, updated_at=_now()))
    return PaperTradingService(repository=repo), repo


def _order(**overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT",
        side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.NEW,
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


_LIMITS = dict(max_order_value=Decimal("100000"), max_position_value=Decimal("100000"), rules_version="v1")


class TestSubmitMarketOrderBuy:
    def test_buy_is_approved_and_filled(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert result.success is True
        assert result.risk_result.approved is True
        assert result.order.status == OrderStatus.FILLED

    def test_buy_opens_long_position(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert result.position.side == PositionSide.LONG
        assert result.position.quantity == Decimal("0.1")
        assert result.position.average_entry_price == Decimal("50000")
        assert repo.get_position("Binance", "BTCUSDT") == result.position

    def test_buy_deducts_notional_and_fee_from_cash(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10000"))
        order = _order(quantity=Decimal("0.1"))
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        # 10000 - (0.1*50000) - (50000*0.1*0.001) = 10000 - 5000 - 5 = 4995
        assert result.cash_balance.total_balance == Decimal("4995")
        assert repo.get_cash_balance("USDT").total_balance == Decimal("4995")

    def test_buy_never_generates_a_trade(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert result.trade is None
        assert repo.fetch_trades() == []

    def test_buy_produces_snapshots(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert result.portfolio_snapshot is not None
        assert result.portfolio_snapshot.total_equity == Decimal("4995") + Decimal("5000")
        assert result.pnl_snapshot is not None
        assert result.pnl_snapshot.unrealized_pnl == Decimal("0")
        assert len(repo.fetch_portfolio_history()) == 1
        assert len(repo.fetch_pnl_history("Binance", "BTCUSDT")) == 1

    def test_buy_persists_execution(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        executions = repo.fetch_executions_by_order("order-1")
        assert len(executions) == 1
        assert executions[0] == result.execution


class TestSubmitMarketOrderSell:
    def _open_position(self, service, timestamp):
        buy_order = _order(id="buy-1", side=OrderSide.BUY, created_at=timestamp, updated_at=timestamp)
        return service.submit_market_order(
            order=buy_order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=timestamp, execution_id="exec-buy", **_LIMITS,
        )

    def test_sell_closes_position_and_generates_trade(self, tmp_path):
        service, repo = _service(tmp_path)
        t0 = _now()
        self._open_position(service, t0)

        t1 = t0 + timedelta(minutes=5)
        sell_order = _order(id="sell-1", side=OrderSide.SELL, created_at=t1, updated_at=t1)
        result = service.submit_market_order(
            order=sell_order, market_price=Decimal("54000"), fee_rate=Decimal("0.001"),
            timestamp=t1, execution_id="exec-sell", trade_id="trade-1", **_LIMITS,
        )
        assert result.success is True
        assert result.position.side == PositionSide.FLAT
        assert result.trade is not None
        assert result.trade.gross_pnl == Decimal("400")
        assert result.trade.fees == Decimal("54000") * Decimal("0.1") * Decimal("0.001")
        assert result.trade.net_pnl == result.trade.gross_pnl - result.trade.fees
        assert repo.fetch_trades() == [result.trade]

    def test_sell_adds_notional_and_subtracts_fee_from_cash(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10000"))
        t0 = _now()
        buy_result = self._open_position(service, t0)
        cash_after_buy = buy_result.cash_balance.total_balance

        t1 = t0 + timedelta(minutes=5)
        sell_order = _order(id="sell-1", side=OrderSide.SELL, created_at=t1, updated_at=t1)
        result = service.submit_market_order(
            order=sell_order, market_price=Decimal("54000"), fee_rate=Decimal("0.001"),
            timestamp=t1, execution_id="exec-sell", trade_id="trade-1", **_LIMITS,
        )
        expected = cash_after_buy + (Decimal("0.1") * Decimal("54000")) - result.execution.fee
        assert result.cash_balance.total_balance == expected

    def test_sell_updates_realized_pnl_to_date(self, tmp_path):
        service, repo = _service(tmp_path)
        t0 = _now()
        self._open_position(service, t0)
        t1 = t0 + timedelta(minutes=5)
        sell_order = _order(id="sell-1", side=OrderSide.SELL, created_at=t1, updated_at=t1)
        result = service.submit_market_order(
            order=sell_order, market_price=Decimal("54000"), fee_rate=Decimal("0.001"),
            timestamp=t1, execution_id="exec-sell", trade_id="trade-1", **_LIMITS,
        )
        assert result.position.realized_pnl_to_date == result.trade.net_pnl
        assert repo.check_position_pnl_consistency("Binance", "BTCUSDT") is True

    def test_sell_without_position_is_rejected(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order(side=OrderSide.SELL)
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", trade_id="trade-1", **_LIMITS,
        )
        assert result.success is False
        assert result.risk_result.code == "SELL_WITHOUT_POSITION"
        assert repo.get_order("order-1") is None

    def test_sell_greater_than_available_is_rejected(self, tmp_path):
        service, repo = _service(tmp_path)
        t0 = _now()
        self._open_position(service, t0)
        t1 = t0 + timedelta(minutes=5)
        sell_order = _order(id="sell-1", side=OrderSide.SELL, quantity=Decimal("999"), created_at=t1, updated_at=t1)
        result = service.submit_market_order(
            order=sell_order, market_price=Decimal("54000"), fee_rate=Decimal("0.001"),
            timestamp=t1, execution_id="exec-sell", trade_id="trade-1", **_LIMITS,
        )
        assert result.success is False
        assert result.risk_result.code == "INSUFFICIENT_AVAILABLE_QUANTITY"


class TestRiskRejection:
    def test_buy_rejected_returns_no_side_effects(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10"))
        order = _order(quantity=Decimal("1"))
        result = service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert result.success is False
        assert result.risk_result.code == "INSUFFICIENT_AVAILABLE_CASH"
        assert result.execution is None
        assert result.position is None
        assert result.trade is None
        assert result.cash_balance is None
        assert result.portfolio_snapshot is None
        assert result.pnl_snapshot is None

    def test_rejected_order_is_not_persisted(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10"))
        order = _order(quantity=Decimal("1"))
        service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert repo.get_order("order-1") is None
        assert repo.fetch_executions_by_order("order-1") == []
        assert repo.get_cash_balance("USDT").total_balance == Decimal("10")

    def test_max_order_value_rejection(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order(quantity=Decimal("1"))
        result = service.submit_market_order(
            order=order, market_price=Decimal("100"), fee_rate=Decimal("0"),
            timestamp=_now(), execution_id="exec-1",
            max_order_value=Decimal("50"), max_position_value=Decimal("100000"), rules_version="v1",
        )
        assert result.success is False
        assert result.risk_result.code == "MAX_ORDER_VALUE_EXCEEDED"


class TestRollback:
    def test_fill_failure_leaves_order_pending_with_reservation_intact(self, tmp_path):
        """Etapa 6.7 (§21.7): submit_market_order() ya no es una única
        transacción -- es accept_market_order() (su propia transacción)
        seguido de fill_pending_order() (otra transacción distinta). Si
        la segunda falla, la primera ya quedó persistida: la orden queda
        legítimamente PENDING con su reserva activa, no "sin persistir"."""
        service, repo = _service(tmp_path, initial_capital=Decimal("100000"))
        order = _order()
        timestamp = _now()

        # Primer submit: éxito, persiste normalmente.
        service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=timestamp, execution_id="exec-1", **_LIMITS,
        )

        # Segundo submit con el mismo execution_id: accept_market_order()
        # se persiste con éxito (PENDING + reserva); fill_pending_order()
        # falla al intentar reutilizar el execution_id ya usado ->
        # IntegrityError dentro de save_fill_transaction.
        other_order = _order(id="order-2")
        with pytest.raises(sqlite3.IntegrityError):
            service.submit_market_order(
                order=other_order, market_price=Decimal("52000"), fee_rate=Decimal("0.001"),
                timestamp=timestamp + timedelta(minutes=1), execution_id="exec-1", **_LIMITS,
            )

        # La segunda orden SÍ quedó persistida, PENDING, con su reserva
        # activa (aceptar y llenar son dos transacciones distintas).
        pending_order = repo.get_order("order-2")
        assert pending_order is not None
        assert pending_order.status == OrderStatus.PENDING
        assert pending_order.reserved_notional is not None
        # Pero no se generó ninguna Execution/Trade para ella: el fill
        # realmente falló y no dejó un estado parcial DENTRO de esa
        # transacción.
        assert repo.fetch_executions_by_order("order-2") == []

        # El estado del primer submit permanece intacto.
        assert repo.get_order("order-1").status == OrderStatus.FILLED
        assert repo.get_position("Binance", "BTCUSDT").quantity == Decimal("0.1")

    def test_missing_cash_balance_raises_without_side_effects(self, tmp_path):
        repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        repo.init()
        service = PaperTradingService(repository=repo)
        order = _order()
        with pytest.raises(ValueError):
            service.submit_market_order(
                order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
                timestamp=_now(), execution_id="exec-1", **_LIMITS,
            )
        assert repo.get_order("order-1") is None


class TestFeeTreatment:
    def test_opening_fee_is_not_double_counted_in_trade(self, tmp_path):
        """Trade.fees debe ser exactamente la fee de cierre; la fee de
        apertura ya se reflejó como salida de efectivo al abrir (§6.2)."""
        service, repo = _service(tmp_path)
        t0 = _now()
        buy_result = service.submit_market_order(
            order=_order(id="buy-1"), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=t0, execution_id="exec-buy", **_LIMITS,
        )
        opening_fee = buy_result.execution.fee

        t1 = t0 + timedelta(minutes=5)
        sell_result = service.submit_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL, created_at=t1, updated_at=t1),
            market_price=Decimal("54000"), fee_rate=Decimal("0.001"),
            timestamp=t1, execution_id="exec-sell", trade_id="trade-1", **_LIMITS,
        )
        closing_fee = sell_result.execution.fee

        assert sell_result.trade.fees == closing_fee
        assert sell_result.trade.fees != opening_fee + closing_fee

        # Reconciliación completa de caja: capital inicial + PnL neto - fee de apertura.
        final_cash = sell_result.cash_balance.total_balance
        assert final_cash == Decimal("10000") + sell_result.trade.net_pnl - opening_fee


class TestNoMutation:
    def test_input_order_is_not_mutated(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        original_status = order.status
        service.submit_market_order(
            order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-1", **_LIMITS,
        )
        assert order.status == original_status

    def test_repository_position_snapshot_before_call_is_not_mutated(self, tmp_path):
        service, repo = _service(tmp_path)
        t0 = _now()
        service.submit_market_order(
            order=_order(id="buy-1"), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=t0, execution_id="exec-buy", **_LIMITS,
        )
        position_before_sell = repo.get_position("Binance", "BTCUSDT")
        quantity_snapshot = position_before_sell.quantity

        t1 = t0 + timedelta(minutes=5)
        service.submit_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL, created_at=t1, updated_at=t1),
            market_price=Decimal("54000"), fee_rate=Decimal("0.001"),
            timestamp=t1, execution_id="exec-sell", trade_id="trade-1", **_LIMITS,
        )
        assert position_before_sell.quantity == quantity_snapshot


# --- Etapa 6.7: ciclo explícito accept / fill / cancel --------------------

class TestAcceptMarketOrderBuy:
    def test_new_becomes_pending_with_reservation(self, tmp_path):
        service, repo = _service(tmp_path)
        result = service.accept_market_order(
            order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), **_LIMITS,
        )
        assert result.success is True
        assert result.order.status == OrderStatus.PENDING
        assert result.cash_balance.reserved_balance == Decimal("5005")

    def test_persists_order_and_cash_balance(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(
            order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), **_LIMITS,
        )
        assert repo.get_order("order-1").status == OrderStatus.PENDING
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")

    def test_does_not_create_execution_trade_or_snapshots(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(
            order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), **_LIMITS,
        )
        assert repo.fetch_executions_by_order("order-1") == []
        assert repo.fetch_trades() == []
        assert repo.fetch_portfolio_history() == []

    def test_risk_rejection_reserves_nothing(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10"))
        result = service.accept_market_order(
            order=_order(quantity=Decimal("1")), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), **_LIMITS,
        )
        assert result.success is False
        assert result.cash_balance is None
        assert repo.get_order("order-1") is None
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")

    def test_duplicate_order_id_raises(self, tmp_path):
        service, repo = _service(tmp_path)
        order = _order()
        service.accept_market_order(order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        with pytest.raises(InvalidOrderStateError):
            service.accept_market_order(order=order, market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)


class TestAcceptMarketOrderSell:
    def _open_position(self, service):
        return service.submit_market_order(
            order=_order(id="buy-1"), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-buy", **_LIMITS,
        )

    def test_new_becomes_pending_with_quantity_reservation(self, tmp_path):
        service, repo = _service(tmp_path)
        self._open_position(service)
        result = service.accept_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL, quantity=Decimal("0.05")),
            market_price=Decimal("54000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS,
        )
        assert result.success is True
        assert result.order.status == OrderStatus.PENDING
        assert result.position.reserved_quantity == Decimal("0.05")

    def test_does_not_reduce_quantity(self, tmp_path):
        service, repo = _service(tmp_path)
        self._open_position(service)
        result = service.accept_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL, quantity=Decimal("0.05")),
            market_price=Decimal("54000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS,
        )
        assert result.position.quantity == Decimal("0.1")

    def test_no_execution_or_trade(self, tmp_path):
        service, repo = _service(tmp_path)
        self._open_position(service)
        service.accept_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL, quantity=Decimal("0.05")),
            market_price=Decimal("54000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS,
        )
        assert repo.fetch_executions_by_order("sell-1") == []
        assert repo.fetch_trades() == []


class TestFillPendingOrderBuy:
    def test_requires_pending_status(self, tmp_path):
        service, repo = _service(tmp_path)
        with pytest.raises(InvalidOrderStateError):
            service.fill_pending_order(order_id="does-not-exist", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())

    def test_releases_reservation(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert result.cash_balance.reserved_balance == Decimal("0")
        assert result.reservation_released is True

    def test_deducts_total_balance(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10000"))
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert result.cash_balance.total_balance == Decimal("4995")

    def test_generates_execution_and_updates_position(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert result.execution is not None
        assert result.position.side == PositionSide.LONG

    def test_order_becomes_filled(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert result.order.status == OrderStatus.FILLED

    def test_produces_snapshots(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert result.portfolio_snapshot is not None
        assert result.pnl_snapshot is not None

    def test_uses_reserved_price_not_a_new_price(self, tmp_path):
        """Política §21.3: fill_pending_order() no recibe market_price; usa
        siempre order.reserved_price."""
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert result.execution.price == Decimal("50000")

    def test_persists_exactly_once(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        assert len(repo.fetch_executions_by_order("order-1")) == 1

    def test_double_fill_raises(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        with pytest.raises(InvalidOrderStateError):
            service.fill_pending_order(order_id="order-1", execution_id="exec-2", fee_rate=Decimal("0.001"), timestamp=_now())


class TestFillPendingOrderSell:
    def test_releases_quantity_reduces_position_credits_cash_generates_trade(self, tmp_path):
        service, repo = _service(tmp_path)
        service.submit_market_order(
            order=_order(id="buy-1"), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-buy", **_LIMITS,
        )
        service.accept_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL), market_price=Decimal("54000"),
            fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS,
        )
        result = service.fill_pending_order(
            order_id="sell-1", execution_id="exec-sell", fee_rate=Decimal("0.001"),
            timestamp=_now(), trade_id="trade-1",
        )
        assert result.position.side == PositionSide.FLAT
        assert result.position.reserved_quantity == Decimal("0")
        assert result.trade is not None
        assert result.trade.gross_pnl == Decimal("400")


class TestCancelPendingOrder:
    def test_requires_pending_status(self, tmp_path):
        service, repo = _service(tmp_path)
        with pytest.raises(InvalidOrderStateError):
            service.cancel_pending_order(order_id="does-not-exist", cancellation_reason="test", timestamp=_now())

    def test_buy_releases_reservation_without_touching_total_balance(self, tmp_path):
        service, repo = _service(tmp_path, initial_capital=Decimal("10000"))
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        result = service.cancel_pending_order(order_id="order-1", cancellation_reason="cambié de opinión", timestamp=_now())
        assert result.order.status == OrderStatus.CANCELLED
        assert result.cash_balance.reserved_balance == Decimal("0")
        assert result.cash_balance.total_balance == Decimal("10000")

    def test_sell_releases_reserved_quantity_without_touching_quantity(self, tmp_path):
        service, repo = _service(tmp_path)
        service.submit_market_order(
            order=_order(id="buy-1"), market_price=Decimal("50000"), fee_rate=Decimal("0.001"),
            timestamp=_now(), execution_id="exec-buy", **_LIMITS,
        )
        service.accept_market_order(
            order=_order(id="sell-1", side=OrderSide.SELL, quantity=Decimal("0.05")),
            market_price=Decimal("54000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS,
        )
        result = service.cancel_pending_order(order_id="sell-1", cancellation_reason="test", timestamp=_now())
        assert result.position.reserved_quantity == Decimal("0")
        assert result.position.quantity == Decimal("0.1")

    def test_no_execution_or_trade_created(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        service.cancel_pending_order(order_id="order-1", cancellation_reason="test", timestamp=_now())
        assert repo.fetch_executions_by_order("order-1") == []
        assert repo.fetch_trades() == []

    def test_requires_cancellation_reason(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        with pytest.raises(ValueError):
            service.cancel_pending_order(order_id="order-1", cancellation_reason="", timestamp=_now())

    def test_double_cancel_raises(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        service.cancel_pending_order(order_id="order-1", cancellation_reason="test", timestamp=_now())
        with pytest.raises(InvalidOrderStateError):
            service.cancel_pending_order(order_id="order-1", cancellation_reason="otra vez", timestamp=_now())

    def test_fill_after_cancel_raises(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        service.cancel_pending_order(order_id="order-1", cancellation_reason="test", timestamp=_now())
        with pytest.raises(InvalidOrderStateError):
            service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())

    def test_cancel_after_fill_raises(self, tmp_path):
        service, repo = _service(tmp_path)
        service.accept_market_order(order=_order(), market_price=Decimal("50000"), fee_rate=Decimal("0.001"), timestamp=_now(), **_LIMITS)
        service.fill_pending_order(order_id="order-1", execution_id="exec-1", fee_rate=Decimal("0.001"), timestamp=_now())
        with pytest.raises(InvalidOrderStateError):
            service.cancel_pending_order(order_id="order-1", cancellation_reason="tarde", timestamp=_now())
