"""
Pruebas para src/paper_trading/composition.py (Composition Root), Etapa 6.5.

Usa SQLitePaperTradingRepository real con tmp_path -- no mockea sqlite3.
No usa datetime.now()/uuid.uuid4() reales: inyecta FixedClock/
DeterministicIdGenerator para que todo sea determinista y verificable.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.composition import (
    PaperTradingContext, build_paper_trading_context, seed_initial_cash_balance,
)
from src.paper_trading.application import PaperTradingApplication
from src.paper_trading.service import PaperTradingService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository
from src.utils.config import PaperTradingConfig


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    def __init__(self):
        self._counter = 0

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def new_order_id(self) -> str:
        return self._next("order")

    def new_execution_id(self) -> str:
        return self._next("exec")

    def new_trade_id(self) -> str:
        return self._next("trade")


class FakePriceProvider:
    """No se usa en las pruebas de composición: ningún caso construye una
    orden real aquí (eso lo cubre test_paper_trading_application.py)."""

    def get_current_price(self, exchange, symbol):
        raise NotImplementedError

    def get_current_prices(self, symbols):
        raise NotImplementedError


def _config(tmp_path, **overrides) -> PaperTradingConfig:
    defaults = dict(
        enabled=True, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
        currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("1000"),
        max_position_value=Decimal("5000"), rules_version="v1",
    )
    defaults.update(overrides)
    return PaperTradingConfig(**defaults)


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestBuildPaperTradingContext:
    def test_builds_sqlite_repository(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context.repository, SQLitePaperTradingRepository)

    def test_repository_is_initialized(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        # get_position no lanza (la tabla ya existe).
        assert context.repository.get_position("Binance", "BTCUSDT") is None

    def test_builds_service(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context.service, PaperTradingService)

    def test_builds_application(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context.application, PaperTradingApplication)

    def test_context_is_a_paper_trading_context(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context, PaperTradingContext)
        assert context.config.enabled is True

    def test_application_shares_the_same_repository(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.application._repository is context.repository
        assert context.service._repository is context.repository

    def test_seeds_initial_capital_with_exact_decimal(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path, initial_capital=Decimal("123456789.123456789")),
            clock=FixedClock(_now()), id_generator=DeterministicIdGenerator(),
            market_price_provider=FakePriceProvider(),
        )
        cash = context.repository.get_cash_balance("USDT")
        assert cash.total_balance == Decimal("123456789.123456789")
        assert cash.reserved_balance == Decimal("0")

    def test_second_initialization_preserves_balance(self, tmp_path):
        config = _config(tmp_path)
        build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        context2 = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context2.repository.get_cash_balance("USDT").total_balance == Decimal("10000")

    def test_third_initialization_preserves_balance(self, tmp_path):
        config = _config(tmp_path)
        for _ in range(3):
            context = build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert context.repository.get_cash_balance("USDT").total_balance == Decimal("10000")

    def test_does_not_duplicate_capital_across_reinitializations(self, tmp_path):
        config = _config(tmp_path)
        for _ in range(3):
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        final = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert final.repository.get_cash_balance("USDT").total_balance == Decimal("10000")

    def test_does_not_erase_existing_orders_on_reinitialization(self, tmp_path):
        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
        from src.paper_trading.models import Order

        order = Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=Decimal("0.1"), status=OrderStatus.NEW,
            source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
        )
        context.repository.save_order(order)

        context2 = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context2.repository.get_order("order-1") == order

    def test_repository_points_to_tmp_path_not_real_database(self, tmp_path):
        import os
        real_db_path = os.path.abspath("data/crypto_data.db")
        before = os.path.getmtime(real_db_path) if os.path.exists(real_db_path) else None

        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )

        assert os.path.abspath(context.repository.db_path) != real_db_path
        after = os.path.getmtime(real_db_path) if os.path.exists(real_db_path) else None
        assert before == after

    def test_timestamp_used_for_seeding_comes_from_injected_clock(self, tmp_path):
        fixed_time = datetime(2030, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(fixed_time),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.repository.get_cash_balance("USDT").updated_at == fixed_time


class TestSeedInitialCashBalance:
    def _repo(self, tmp_path) -> SQLitePaperTradingRepository:
        repository = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        repository.init()
        return repository

    def test_creates_balance_when_missing(self, tmp_path):
        repository = self._repo(tmp_path)
        cash = seed_initial_cash_balance(repository, Decimal("5000"), "USDT", _now())
        assert cash.total_balance == Decimal("5000")
        assert cash.reserved_balance == Decimal("0")

    def test_returns_existing_balance_without_overwriting(self, tmp_path):
        repository = self._repo(tmp_path)
        seed_initial_cash_balance(repository, Decimal("5000"), "USDT", _now())
        result = seed_initial_cash_balance(repository, Decimal("999999"), "USDT", _now())
        assert result.total_balance == Decimal("5000")
        assert repository.get_cash_balance("USDT").total_balance == Decimal("5000")

    def test_rejects_zero_initial_capital(self, tmp_path):
        repository = self._repo(tmp_path)
        with pytest.raises(ValueError):
            seed_initial_cash_balance(repository, Decimal("0"), "USDT", _now())

    def test_rejects_negative_initial_capital(self, tmp_path):
        repository = self._repo(tmp_path)
        with pytest.raises(ValueError):
            seed_initial_cash_balance(repository, Decimal("-1"), "USDT", _now())

    def test_uses_injected_timestamp_not_system_clock(self, tmp_path):
        repository = self._repo(tmp_path)
        fixed_time = datetime(2031, 3, 3, tzinfo=timezone.utc)
        cash = seed_initial_cash_balance(repository, Decimal("100"), "USDT", fixed_time)
        assert cash.updated_at == fixed_time


class TestInvalidConfiguration:
    def test_missing_cash_balance_seed_after_disabling_is_still_seeded(self, tmp_path):
        """enabled=False no cambia el comportamiento de build_paper_trading_context
        (la decisión de no construir nada si enabled=False es responsabilidad
        de main.py/build_paper_trading(), no de esta función de más bajo nivel)."""
        context = build_paper_trading_context(
            config=_config(tmp_path, enabled=False), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.repository.get_cash_balance("USDT") is not None
