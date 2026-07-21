"""
Pruebas para src/paper_trading/application.py (PaperTradingApplication), Etapa 6.5.

Usa SQLitePaperTradingRepository real (tmp_path) + PaperTradingService
real; inyecta FixedClock/DeterministicIdGenerator (nunca
datetime.now()/uuid.uuid4() reales) y un FakePriceProvider en memoria
(nunca Binance/requests).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.paper_trading.application import PaperTradingApplication, PaperTradingDisabledError
from src.paper_trading.enums import OrderSide, OrderStatus, PositionSide
from src.paper_trading.models import CashBalance
from src.paper_trading.service import PaperTradingService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.utils.config import PaperTradingConfig


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    """Un contador independiente por tipo de id, para que las pruebas puedan
    afirmar valores exactos sin acoplarse al orden interno de llamadas de
    PaperTradingApplication."""

    def __init__(self):
        self._counters = {"order": 0, "exec": 0, "trade": 0, "audit": 0}

    def _next(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]}"

    @property
    def total_calls(self) -> int:
        return sum(self._counters.values())

    def new_order_id(self) -> str:
        return self._next("order")

    def new_execution_id(self) -> str:
        return self._next("exec")

    def new_trade_id(self) -> str:
        return self._next("trade")

    def new_reconciliation_audit_id(self) -> str:
        return self._next("audit")


class FakePriceProvider:
    """Precios en memoria, nunca Binance/requests: prueba solo la orquestación."""

    def __init__(self, prices: dict):
        self._prices = dict(prices)
        self.queried_symbols: list = []

    def get_current_price(self, exchange, symbol):
        key = (exchange, symbol)
        self.queried_symbols.append(key)
        if key not in self._prices:
            raise ValueError(f"No hay precio para {key}.")
        return self._prices[key]

    def get_current_prices(self, symbols):
        return {key: self.get_current_price(*key) for key in symbols}


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _config(**overrides) -> PaperTradingConfig:
    defaults = dict(
        enabled=True, database_path="unused", initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("100000"),
        max_position_value=Decimal("100000"), rules_version="v1",
    )
    defaults.update(overrides)
    return PaperTradingConfig(**defaults)


def _app(tmp_path, prices=None, config=None):
    repository = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repository.init()
    repository.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))

    service = PaperTradingService(repository=repository)
    clock = FixedClock(_now())
    id_generator = DeterministicIdGenerator()
    default_prices = {("Binance", "BTCUSDT"): Decimal("50000")}
    price_provider = FakePriceProvider(default_prices if prices is None else prices)
    cfg = config or _config()

    application = PaperTradingApplication(
        service=service, repository=repository, price_provider=price_provider,
        clock=clock, id_generator=id_generator, config=cfg,
    )
    return application, repository, price_provider, id_generator


class TestBuyManualOrder:
    def test_buy_succeeds_and_returns_full_result(self, tmp_path):
        application, repository, price_provider, _ = _app(tmp_path)

        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert result.success is True
        assert result.order.status == OrderStatus.FILLED
        assert result.order.order_type.value == "MARKET"
        assert ("Binance", "BTCUSDT") in price_provider.queried_symbols

    def test_buy_generates_order_id_and_execution_id_but_no_trade_id(self, tmp_path):
        application, repository, _, id_generator = _app(tmp_path)

        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert result.order.id == "order-1"
        assert result.execution.id == "exec-1"
        assert result.trade is None

    def test_buy_persists_the_order(self, tmp_path):
        application, repository, _, _ = _app(tmp_path)

        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert repository.get_order(result.order.id) == result.order

    def test_buy_uses_market_order_type(self, tmp_path):
        application, repository, _, _ = _app(tmp_path)
        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        assert result.order.order_type.value == "MARKET"


class TestSellManualOrder:
    def _open_position(self, application):
        return application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

    def test_sell_generates_trade_id_and_closes_position(self, tmp_path):
        application, repository, price_provider, id_generator = _app(
            tmp_path, prices={("Binance", "BTCUSDT"): Decimal("50000")},
        )
        self._open_position(application)

        price_provider._prices[("Binance", "BTCUSDT")] = Decimal("54000")
        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL, quantity=Decimal("0.1"),
        )

        assert result.success is True
        assert result.trade is not None
        assert result.trade.id == "trade-1"
        assert result.position.side == PositionSide.FLAT

    def test_sell_persists_result(self, tmp_path):
        application, repository, price_provider, _ = _app(tmp_path)
        self._open_position(application)
        price_provider._prices[("Binance", "BTCUSDT")] = Decimal("54000")

        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL, quantity=Decimal("0.1"),
        )

        assert repository.fetch_trades() == [result.trade]


class TestRiskRejection:
    def test_returns_success_false_without_hiding_risk_result(self, tmp_path):
        application, repository, _, _ = _app(
            tmp_path, config=_config(max_order_value=Decimal("1")),
        )

        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert result.success is False
        assert result.risk_result is not None
        assert result.risk_result.approved is False

    def test_rejected_order_is_not_persisted(self, tmp_path):
        application, repository, _, _ = _app(
            tmp_path, config=_config(max_order_value=Decimal("1")),
        )

        application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert repository.fetch_orders() == []


class TestDisabled:
    def test_raises_and_does_not_query_prices_or_generate_ids(self, tmp_path):
        application, repository, price_provider, id_generator = _app(
            tmp_path, config=_config(enabled=False),
        )

        with pytest.raises(PaperTradingDisabledError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )

        assert price_provider.queried_symbols == []
        assert id_generator.total_calls == 0

    def test_does_not_write_anything(self, tmp_path):
        application, repository, _, _ = _app(tmp_path, config=_config(enabled=False))

        with pytest.raises(PaperTradingDisabledError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )

        assert repository.fetch_orders() == []


class TestInvalidInput:
    def test_empty_exchange_is_rejected(self, tmp_path):
        application, _, _, _ = _app(tmp_path)
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )

    def test_empty_symbol_is_rejected(self, tmp_path):
        application, _, _, _ = _app(tmp_path)
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )

    def test_zero_quantity_is_rejected(self, tmp_path):
        application, _, _, _ = _app(tmp_path)
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0"),
            )

    def test_negative_quantity_is_rejected(self, tmp_path):
        application, _, _, _ = _app(tmp_path)
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("-1"),
            )

    def test_invalid_side_is_rejected(self, tmp_path):
        application, _, _, _ = _app(tmp_path)
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side="BUY", quantity=Decimal("0.1"),
            )

    def test_missing_price_is_rejected(self, tmp_path):
        application, _, _, _ = _app(tmp_path, prices={})
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )

    def test_zero_price_is_rejected(self, tmp_path):
        """FakePriceProvider no valida price > 0 por sí solo (eso lo hace
        RepositoryMarketPriceProvider en producción, ver
        test_paper_trading_price_provider.py); aquí, un precio de 0 que de
        todas formas llega hasta RiskEngine.validate_order() es rechazado
        por esa guarda (market_price <= 0)."""
        application, _, _, _ = _app(tmp_path, prices={("Binance", "BTCUSDT"): Decimal("0")})
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )


class TestMultiSymbolPricing:
    def test_fetches_prices_for_all_open_positions(self, tmp_path):
        application, repository, price_provider, _ = _app(
            tmp_path,
            prices={
                ("Binance", "BTCUSDT"): Decimal("50000"),
                ("Binance", "ETHUSDT"): Decimal("2000"),
            },
        )
        application.submit_manual_market_order(
            exchange="Binance", symbol="ETHUSDT", side=OrderSide.BUY, quantity=Decimal("1"),
        )
        price_provider.queried_symbols.clear()

        application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert ("Binance", "ETHUSDT") in price_provider.queried_symbols
        assert ("Binance", "BTCUSDT") in price_provider.queried_symbols

    def test_does_not_query_price_for_flat_positions(self, tmp_path):
        application, repository, price_provider, _ = _app(
            tmp_path,
            prices={
                ("Binance", "BTCUSDT"): Decimal("54000"),
                ("Binance", "ETHUSDT"): Decimal("2000"),
            },
        )
        application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL, quantity=Decimal("0.1"),
        )
        assert repository.get_position("Binance", "BTCUSDT").side == PositionSide.FLAT
        price_provider.queried_symbols.clear()

        application.submit_manual_market_order(
            exchange="Binance", symbol="ETHUSDT", side=OrderSide.BUY, quantity=Decimal("1"),
        )

        assert ("Binance", "BTCUSDT") not in price_provider.queried_symbols

    def test_passes_full_current_prices_to_service(self, tmp_path):
        application, repository, price_provider, _ = _app(
            tmp_path,
            prices={
                ("Binance", "BTCUSDT"): Decimal("50000"),
                ("Binance", "ETHUSDT"): Decimal("2000"),
            },
        )
        application.submit_manual_market_order(
            exchange="Binance", symbol="ETHUSDT", side=OrderSide.BUY, quantity=Decimal("1"),
        )
        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        assert result.portfolio_snapshot.positions_value == Decimal("50000") * Decimal("0.1") + Decimal("2000") * Decimal("1")

    def test_missing_price_for_other_open_position_aborts_before_persisting(self, tmp_path):
        application, repository, price_provider, _ = _app(
            tmp_path,
            prices={
                ("Binance", "BTCUSDT"): Decimal("50000"),
                ("Binance", "ETHUSDT"): Decimal("2000"),
            },
        )
        application.submit_manual_market_order(
            exchange="Binance", symbol="ETHUSDT", side=OrderSide.BUY, quantity=Decimal("1"),
        )
        del price_provider._prices[("Binance", "ETHUSDT")]

        second_order_id_before = repository.fetch_orders()
        with pytest.raises(ValueError):
            application.submit_manual_market_order(
                exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
            )

        # Ninguna orden nueva de BTCUSDT quedó persistida.
        assert repository.get_position("Binance", "BTCUSDT") is None


class TestClockAndIdGenerator:
    def test_uses_fixed_clock_timestamp_exactly(self, tmp_path):
        fixed_time = datetime(2029, 6, 15, 8, 30, tzinfo=timezone.utc)
        repository = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        repository.init()
        repository.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        service = PaperTradingService(repository=repository)
        application = PaperTradingApplication(
            service=service, repository=repository,
            price_provider=FakePriceProvider({("Binance", "BTCUSDT"): Decimal("50000")}),
            clock=FixedClock(fixed_time), id_generator=DeterministicIdGenerator(), config=_config(),
        )

        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        assert result.order.created_at == fixed_time
        assert result.order.updated_at == fixed_time
        assert result.execution.executed_at == fixed_time

    def test_uses_deterministic_ids_exactly(self, tmp_path):
        application, _, _, _ = _app(tmp_path)
        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        assert result.order.id == "order-1"
        assert result.execution.id == "exec-1"

    def test_module_does_not_call_datetime_now_or_uuid4_directly(self):
        import src.paper_trading.application as module
        source = open(module.__file__, encoding="utf-8").read()
        assert "datetime.now(" not in source
        assert "uuid.uuid4(" not in source


class TestNoMutation:
    def test_service_result_is_returned_unmodified(self, tmp_path):
        application, repository, _, _ = _app(tmp_path)
        result = application.submit_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        # El resultado que devuelve la Application debe coincidir exactamente
        # con lo que ya persistió el Service (nada se recalcula encima).
        assert repository.get_order(result.order.id) == result.order
        assert repository.get_position("Binance", "BTCUSDT") == result.position


# --- Etapa 6.7: ciclo explícito accept / fill / cancel --------------------

class TestAcceptManualMarketOrder:
    def test_accept_buy_leaves_order_pending_with_reservation(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        assert result.success is True
        assert result.order.status == OrderStatus.PENDING
        assert result.order.id == "order-1"

    def test_accept_sell_reserves_quantity(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        application.submit_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"))
        result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL, quantity=Decimal("0.05"),
        )
        assert result.success is True
        assert result.position.reserved_quantity == Decimal("0.05")

    def test_disabled_raises_before_anything(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path, config=_config(enabled=False))
        with pytest.raises(PaperTradingDisabledError):
            application.accept_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"))
        assert price_provider.queried_symbols == []
        assert id_generator.total_calls == 0

    def test_risk_rejection_returns_success_false(self, tmp_path):
        application, repository, _, _ = _app(tmp_path, config=_config(max_order_value=Decimal("1")))
        result = application.accept_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"))
        assert result.success is False
        assert repository.fetch_orders() == []


class TestFillManualPendingOrder:
    def test_fills_pending_order_without_querying_traded_symbol_price(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        price_provider.queried_symbols.clear()

        result = application.fill_manual_pending_order(order_id=accept_result.order.id)

        assert result.order.status == OrderStatus.FILLED
        assert ("Binance", "BTCUSDT") not in price_provider.queried_symbols

    def test_fill_generates_execution_id_but_no_trade_id_for_buy(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        result = application.fill_manual_pending_order(order_id=accept_result.order.id)
        assert result.execution is not None
        assert result.trade is None

    def test_fill_generates_trade_id_for_sell(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        application.submit_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"))
        price_provider._prices[("Binance", "BTCUSDT")] = Decimal("54000")
        accept_result = application.accept_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL, quantity=Decimal("0.1"))

        result = application.fill_manual_pending_order(order_id=accept_result.order.id)

        assert result.trade is not None

    def test_disabled_raises_before_anything(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"))

        disabled_application, _, disabled_price_provider, disabled_id_generator = _app(tmp_path, config=_config(enabled=False))
        with pytest.raises(PaperTradingDisabledError):
            disabled_application.fill_manual_pending_order(order_id=accept_result.order.id)
        assert disabled_id_generator.total_calls == 0


class TestCancelManualPendingOrder:
    def test_cancels_pending_order_without_querying_any_price(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        price_provider.queried_symbols.clear()

        result = application.cancel_manual_pending_order(order_id=accept_result.order.id, cancellation_reason="cambié de opinión")

        assert result.order.status == OrderStatus.CANCELLED
        assert price_provider.queried_symbols == []

    def test_releases_reservation(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        result = application.cancel_manual_pending_order(order_id=accept_result.order.id, cancellation_reason="test")
        assert result.cash_balance.reserved_balance == Decimal("0")

    def test_disabled_raises_before_anything(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"))

        disabled_application, _, disabled_price_provider, _ = _app(tmp_path, config=_config(enabled=False))
        with pytest.raises(PaperTradingDisabledError):
            disabled_application.cancel_manual_pending_order(order_id=accept_result.order.id, cancellation_reason="test")
        assert disabled_price_provider.queried_symbols == []


class TestReinitializationAfterRestart:
    def test_accept_then_new_application_instance_can_still_fill(self, tmp_path):
        """Simula un reinicio: se construye una Application NUEVA sobre el
        mismo repositorio y logra llenar una orden aceptada por la
        instancia anterior."""
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )

        from src.paper_trading.service import PaperTradingService
        new_application = PaperTradingApplication(
            service=PaperTradingService(repository=repository),
            repository=repository, price_provider=FakePriceProvider({("Binance", "BTCUSDT"): Decimal("50000")}),
            clock=FixedClock(_now()), id_generator=DeterministicIdGenerator(), config=_config(),
        )
        result = new_application.fill_manual_pending_order(order_id=accept_result.order.id)
        assert result.order.status == OrderStatus.FILLED


class TestInspectReconciliation:
    def test_inspect_on_clean_account_is_consistent(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        report = application.inspect_reconciliation()
        assert report.is_consistent is True

    def test_inspect_never_queries_prices(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        application.inspect_reconciliation()
        assert price_provider.queried_symbols == []

    def test_inspect_does_not_require_enabled(self, tmp_path):
        """Política documentada (§22): reconciliar no es una acción de
        trading nueva, sigue disponible con enabled=False."""
        application, repository, price_provider, id_generator = _app(
            tmp_path, config=_config(enabled=False),
        )
        report = application.inspect_reconciliation()
        assert report is not None

    def test_inspect_uses_injected_clock(self, tmp_path):
        fixed = datetime(2030, 5, 5, tzinfo=timezone.utc)
        repository = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        repository.init()
        repository.save_cash_balance(CashBalance(total_balance=Decimal("10000"), updated_at=_now()))
        application = PaperTradingApplication(
            service=PaperTradingService(repository=repository), repository=repository,
            price_provider=FakePriceProvider({}), clock=FixedClock(fixed),
            id_generator=DeterministicIdGenerator(), config=_config(),
        )
        report = application.inspect_reconciliation()
        assert report.generated_at == fixed


class TestRepairReconciliation:
    def test_dry_run_by_default(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        repository.save_cash_balance(CashBalance(
            total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        result = application.repair_reconciliation()
        assert result.dry_run is True
        assert repository.get_cash_balance("USDT").reserved_balance == Decimal("999")

    def test_apply_writes_when_dry_run_false(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        repository.save_cash_balance(CashBalance(
            total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        result = application.repair_reconciliation(dry_run=False)
        assert result.dry_run is False
        assert repository.get_cash_balance("USDT").reserved_balance == Decimal("0")

    def test_uses_id_generator_for_audit(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        application.repair_reconciliation()
        assert id_generator._counters["audit"] == 1

    def test_does_not_query_prices(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        application.repair_reconciliation()
        assert price_provider.queried_symbols == []

    def test_does_not_generate_order_execution_or_trade_ids(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        application.repair_reconciliation()
        assert id_generator._counters["order"] == 0
        assert id_generator._counters["exec"] == 0
        assert id_generator._counters["trade"] == 0

    def test_does_not_touch_order_status(self, tmp_path):
        application, repository, price_provider, id_generator = _app(tmp_path)
        accept_result = application.accept_manual_market_order(
            exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.1"),
        )
        application.repair_reconciliation(dry_run=False)
        assert repository.get_order(accept_result.order.id).status == OrderStatus.PENDING

    def test_does_not_require_enabled(self, tmp_path):
        application, repository, price_provider, id_generator = _app(
            tmp_path, config=_config(enabled=False),
        )
        repository.save_cash_balance(CashBalance(
            total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))
        result = application.repair_reconciliation(dry_run=False)
        assert result.success is True
        assert repository.get_cash_balance("USDT").reserved_balance == Decimal("0")
