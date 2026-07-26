"""
Pruebas para src/paper_trading/composition.py (Composition Root), Etapa 6.5.

Usa SQLitePaperTradingRepository real con tmp_path -- no mockea sqlite3.
No usa datetime.now()/uuid.uuid4() reales: inyecta FixedClock/
DeterministicIdGenerator para que todo sea determinista y verificable.
"""

import math
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

    def new_reconciliation_audit_id(self) -> str:
        return self._next("audit")

    def new_inspection_run_id(self) -> str:
        return self._next("run")

    def new_inspection_alert_id(self) -> str:
        return self._next("alert")


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


class TestReservationEngineInjection:
    def test_service_uses_the_real_reservation_engine(self, tmp_path):
        from src.paper_trading.reservation_engine import ReservationEngine
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.service._reservation_engine is ReservationEngine


class TestReservationSurvivesRestart:
    """Etapa 6.7 (Paso 22): una orden PENDING con reserva debe conservarse
    exactamente igual al reconstruir la Composition Root (simulando un
    reinicio del proceso), sin duplicar ni perder la reserva."""

    def test_buy_pending_reservation_survives_reinitialization(self, tmp_path):
        from decimal import Decimal as D
        from datetime import datetime as DT
        from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
        from src.paper_trading.models import Order

        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        now = _now()
        order = Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=D("0.1"), status=OrderStatus.NEW,
            source=OrderSource.MANUAL, created_at=now, updated_at=now,
        )
        context.service.accept_market_order(
            order=order, market_price=D("50000"), fee_rate=D("0.001"), timestamp=now,
            max_order_value=D("100000"), max_position_value=D("100000"), rules_version="v1",
        )

        # "Reinicio": se reconstruye todo el contexto sobre la misma base.
        restarted_context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )

        restarted_order = restarted_context.repository.get_order("order-1")
        assert restarted_order.status == OrderStatus.PENDING
        assert restarted_order.reserved_notional == D("5000")
        assert restarted_context.repository.get_cash_balance("USDT").reserved_balance == D("5005")
        # El capital inicial no se reinicia ni se duplica.
        assert restarted_context.repository.get_cash_balance("USDT").total_balance == D("10000")

    def test_filling_after_restart_releases_correctly(self, tmp_path):
        from decimal import Decimal as D
        from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
        from src.paper_trading.models import Order

        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        now = _now()
        order = Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=D("0.1"), status=OrderStatus.NEW,
            source=OrderSource.MANUAL, created_at=now, updated_at=now,
        )
        context.service.accept_market_order(
            order=order, market_price=D("50000"), fee_rate=D("0.001"), timestamp=now,
            max_order_value=D("100000"), max_position_value=D("100000"), rules_version="v1",
        )

        restarted_context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        result = restarted_context.service.fill_pending_order(
            order_id="order-1", execution_id="exec-1", fee_rate=D("0.001"), timestamp=_now(),
        )
        assert result.order.status == OrderStatus.FILLED
        assert result.cash_balance.reserved_balance == D("0")

    def test_cancelling_after_restart_releases_correctly(self, tmp_path):
        from decimal import Decimal as D
        from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
        from src.paper_trading.models import Order

        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        now = _now()
        order = Order(
            id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
            order_type=OrderType.MARKET, quantity=D("0.1"), status=OrderStatus.NEW,
            source=OrderSource.MANUAL, created_at=now, updated_at=now,
        )
        context.service.accept_market_order(
            order=order, market_price=D("50000"), fee_rate=D("0.001"), timestamp=now,
            max_order_value=D("100000"), max_position_value=D("100000"), rules_version="v1",
        )

        restarted_context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        result = restarted_context.service.cancel_pending_order(
            order_id="order-1", cancellation_reason="reinicio", timestamp=_now(),
        )
        assert result.order.status == OrderStatus.CANCELLED
        assert result.cash_balance.reserved_balance == D("0")
        assert result.cash_balance.total_balance == D("10000")


class TestReconciliationServiceInjection:
    def test_context_exposes_a_reconciliation_service(self, tmp_path):
        from src.paper_trading.reconciliation_service import ReconciliationService
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context.reconciliation_service, ReconciliationService)

    def test_service_uses_the_real_reconciliation_engine(self, tmp_path):
        from src.paper_trading.reconciliation_engine import ReconciliationEngine
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.reconciliation_service._engine is ReconciliationEngine

    def test_application_exposes_reconciliation_use_cases(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert hasattr(context.application, "inspect_reconciliation")
        assert hasattr(context.application, "repair_reconciliation")


class TestBuildDoesNotRunReconciliation:
    """Paso 24: build_paper_trading_context() nunca ejecuta inspect()/repair()."""

    def test_build_does_not_inspect_or_repair_on_construction(self, tmp_path, monkeypatch):
        from src.paper_trading import reconciliation_service as reconciliation_service_module

        calls = []
        monkeypatch.setattr(
            reconciliation_service_module.ReconciliationService, "inspect",
            lambda self, timestamp: calls.append("inspect"),
        )
        monkeypatch.setattr(
            reconciliation_service_module.ReconciliationService, "repair",
            lambda self, *a, **k: calls.append("repair"),
        )

        build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert calls == []

    def test_restart_over_inconsistent_data_leaves_it_untouched(self, tmp_path):
        """Reconstruir la Composition Root sobre datos con reservas
        inconsistentes no las repara: build_paper_trading_context() no
        detecta ni corrige nada por sí sola (Paso 24)."""
        from decimal import Decimal as D
        from src.paper_trading.models import CashBalance

        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        corrupted = CashBalance(
            currency="USDT", total_balance=D("10000"), reserved_balance=D("999"), updated_at=_now(),
        )
        context.repository.save_cash_balance(corrupted)

        restarted_context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert restarted_context.repository.get_cash_balance("USDT").reserved_balance == D("999")
        assert restarted_context.repository.get_cash_balance("USDT").total_balance == D("10000")


class TestInspectionServicesInjection:
    def test_context_exposes_inspection_services(self, tmp_path):
        from src.paper_trading.alert_delivery_service import AlertDeliveryService
        from src.paper_trading.inspection_job import InspectionJob
        from src.paper_trading.inspection_service import InspectionService

        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context.inspection_service, InspectionService)
        assert isinstance(context.alert_delivery_service, AlertDeliveryService)
        assert isinstance(context.inspection_job, InspectionJob)

    def test_application_exposes_inspection_use_cases(self, tmp_path):
        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert hasattr(context.application, "run_reconciliation_inspection")
        assert hasattr(context.application, "deliver_pending_reconciliation_alerts")
        assert hasattr(context.application, "fetch_reconciliation_inspection_history")


class TestBuildDoesNotRunInspection:
    """Paso 24 (extendido a la Etapa 6.9): build_paper_trading_context()
    nunca ejecuta inspect()/repair()/run_once()/entrega alguna."""

    def test_build_does_not_call_run_once_inspect_or_deliver(self, tmp_path, monkeypatch):
        from src.paper_trading import alert_delivery_service as alert_delivery_module
        from src.paper_trading import inspection_job as inspection_job_module
        from src.paper_trading import inspection_service as inspection_service_module

        calls = []
        monkeypatch.setattr(
            inspection_job_module.InspectionJob, "run_once", lambda self: calls.append("run_once"),
        )
        monkeypatch.setattr(
            inspection_service_module.InspectionService, "run_inspection",
            lambda self, *a, **k: calls.append("run_inspection"),
        )
        monkeypatch.setattr(
            alert_delivery_module.AlertDeliveryService, "deliver_pending_alerts",
            lambda self, *a, **k: calls.append("deliver_pending_alerts"),
        )

        build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert calls == []

    def test_disabled_reconciliation_inspection_config_has_no_effect_on_build(self, tmp_path):
        from src.utils.config import ReconciliationInspectionConfig

        config = _config(tmp_path, reconciliation_inspection=ReconciliationInspectionConfig(enabled=False))
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.repository.fetch_inspection_runs(limit=None) == []


class TestInspectionSurvivesRestart:
    def test_restart_preserves_inspection_history(self, tmp_path):
        from decimal import Decimal as D

        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        run = context.application.run_reconciliation_inspection()

        restarted_context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        history = restarted_context.application.fetch_reconciliation_inspection_history()
        assert [r.id for r in history] == [run.id]
        # El capital inicial sigue siendo idempotente tras el reinicio.
        assert restarted_context.repository.get_cash_balance("USDT").total_balance == D("10000")

    def test_dashboard_module_is_never_imported_by_composition(self):
        import src.paper_trading.composition as module
        source = open(module.__file__, encoding="utf-8").read()
        assert "dashboard" not in source.lower()


class TestNotificationChannelWiring:
    """Etapa 6.10: Composition Root arma el CompositeNotificationChannel
    según config.inspection_notifications; ver docs/ARQUITECTURA_PAPER_TRADING.md §24."""

    def test_default_config_wires_only_logging_channel(self, tmp_path):
        from src.paper_trading.notification_channels import CompositeNotificationChannel, LoggingNotificationChannel

        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channel = context.alert_delivery_service._channel
        assert isinstance(channel, CompositeNotificationChannel)
        assert len(channel._channels) == 1
        assert isinstance(channel._channels[0], LoggingNotificationChannel)

    def test_all_channels_disabled_produces_empty_composite(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig

        config = _config(tmp_path, inspection_notifications=InspectionNotificationsConfig(logging=False))
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.alert_delivery_service._channel._channels == []

    def test_alert_delivery_service_never_imports_notification_channels_by_name(self):
        """AlertDeliveryService no debe conocer ningún canal concreto por
        nombre (nunca un if/isinstance por TIPO DE CANAL, ver §24.2).

        Etapa 6.11.1 (§26.x): el servicio ahora valida
        `isinstance(message, NotificationMessage)` -- una validación del
        contrato de la plantilla, no una rama por tipo de canal. Esa
        única forma de `isinstance(...)` es la excepción explícitamente
        permitida; ninguna otra puede aparecer, y ninguna puede mencionar
        un canal concreto."""
        import re

        import src.paper_trading.alert_delivery_service as module
        source = open(module.__file__, encoding="utf-8").read()
        import_lines = [
            line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
        ]
        forbidden_channel_names = (
            "LoggingNotificationChannel", "EmailNotificationChannel", "SlackNotificationChannel",
            "TelegramNotificationChannel", "WebhookNotificationChannel", "CompositeNotificationChannel",
        )
        for forbidden in forbidden_channel_names:
            assert not any(forbidden in line for line in import_lines)

        isinstance_calls = re.findall(r"isinstance\(([^)]*)\)", source)
        assert isinstance_calls == ["message, NotificationMessage"]
        for call in isinstance_calls:
            for forbidden in forbidden_channel_names:
                assert forbidden not in call


class TestPlaceholderChannelsBlockedAtStartup:
    """Corrección 3 (Etapa 6.10.1, §25.3): habilitar un canal placeholder
    debe fallar de inmediato al construir la Composition Root, con un
    mensaje que identifica el canal -- nunca esperar a la primera alerta."""

    def test_webhook_true_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig

        config = _config(tmp_path, inspection_notifications=InspectionNotificationsConfig(webhook=True))
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "WebhookNotificationChannel" in str(exc_info.value)

    def test_logging_true_works(self, tmp_path):
        config = _config(tmp_path)  # default: logging=True, resto False
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context is not None

    def test_all_channels_disabled_is_explicit_and_does_not_fail(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig

        config = _config(tmp_path, inspection_notifications=InspectionNotificationsConfig(logging=False))
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context.alert_delivery_service._channel._channels == []
        result = context.application.deliver_pending_reconciliation_alerts()
        assert result.failed_count == 0


class TestTelegramChannelWiring:
    """Etapa 6.12 (§27): TelegramNotificationChannel deja de ser
    placeholder -- se construye e inyecta como canal real cuando
    inspection_notifications.telegram=True y las credenciales son
    válidas."""

    def test_disabled_by_default_telegram_not_constructed(self, tmp_path):
        from src.paper_trading.notification_channels import TelegramNotificationChannel

        config = _config(tmp_path)  # default: telegram=False
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert not any(isinstance(c, TelegramNotificationChannel) for c in channels)

    def test_disabled_by_default_does_not_require_token_or_chat_id(self, tmp_path):
        from src.utils.config import TelegramSettings

        config = _config(tmp_path, telegram=TelegramSettings(bot_token=None, chat_id=None))
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context is not None

    def test_disabled_preserves_previous_behavior(self, tmp_path):
        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        from src.paper_trading.notification_channels import LoggingNotificationChannel

        channels = context.alert_delivery_service._channel._channels
        assert len(channels) == 1
        assert isinstance(channels[0], LoggingNotificationChannel)

    def test_enabled_and_configured_builds_telegram_channel(self, tmp_path):
        from src.paper_trading.notification_channels import TelegramNotificationChannel
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token="tok", chat_id="chat", timeout_seconds=7.5),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        telegram_channels = [c for c in channels if isinstance(c, TelegramNotificationChannel)]
        assert len(telegram_channels) == 1

    def test_channel_does_not_retain_the_token(self, tmp_path):
        """Etapa 6.12.1 (§27.x): el canal no conserva el token -- solo
        posee `transport`/`clock`."""
        from src.paper_trading.notification_channels import TelegramNotificationChannel
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token="tok", chat_id="chat"),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        telegram_channel = next(c for c in channels if isinstance(c, TelegramNotificationChannel))
        assert set(vars(telegram_channel).keys()) == {"_transport", "_clock"}
        assert "tok" not in repr(telegram_channel)

    def test_transport_receives_the_correct_configuration(self, tmp_path, monkeypatch):
        """Confirma la configuración correcta sin inspeccionar
        directamente el atributo sensible en el objeto ya construido:
        se intercepta la llamada al constructor del transporte (spy),
        no se lee `bot_token` de un objeto vivo."""
        import src.paper_trading.composition as composition_module
        from src.paper_trading.telegram_transport import TelegramCredentials, UrllibTelegramTransport
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        captured = {}
        real_transport_cls = UrllibTelegramTransport

        def _spy_transport(*, credentials, timeout_seconds=10.0):
            captured["chat_id"] = credentials.chat_id
            captured["bot_token_matches_expected"] = (credentials.bot_token == "tok-esperado")
            captured["timeout_seconds"] = timeout_seconds
            return real_transport_cls(credentials=credentials, timeout_seconds=timeout_seconds)

        monkeypatch.setattr(composition_module, "UrllibTelegramTransport", _spy_transport)

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token="tok-esperado", chat_id="chat-esperado", timeout_seconds=7.5),
        )
        build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert captured["chat_id"] == "chat-esperado"
        assert captured["bot_token_matches_expected"] is True
        assert captured["timeout_seconds"] == 7.5

    def test_enabled_incorporates_into_composite_after_logging(self, tmp_path):
        from src.paper_trading.notification_channels import LoggingNotificationChannel, TelegramNotificationChannel
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(logging=True, telegram=True),
            telegram=TelegramSettings(bot_token="tok", chat_id="chat"),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert [type(c) for c in channels] == [LoggingNotificationChannel, TelegramNotificationChannel]

    def test_enabled_without_token_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token=None, chat_id="chat"),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "bot token" in str(exc_info.value).lower()

    def test_enabled_without_chat_id_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token="tok", chat_id=None),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "chat id" in str(exc_info.value).lower()

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.5, math.nan, math.inf, -math.inf])
    def test_enabled_with_invalid_timeout_fails_to_build_context(self, tmp_path, bad_timeout):
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token="tok", chat_id="chat", timeout_seconds=bad_timeout),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "timeout" in str(exc_info.value).lower()

    def test_telegram_error_never_includes_the_token(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(telegram=True),
            telegram=TelegramSettings(bot_token=None, chat_id="chat"),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "chat" not in str(exc_info.value)  # el chat_id real tampoco se filtra por accidente

    def test_other_placeholders_remain_blocked_at_startup(self, tmp_path):
        """Etapa 6.12 (§27, punto 20), actualizada en 6.13 (§28, punto 22)
        y en 6.14 (§29, punto 28): solo Webhook sigue bloqueado como
        placeholder -- Telegram, Slack y Email ya son canales reales."""
        from src.utils.config import InspectionNotificationsConfig

        for flag, class_name in (
            ("webhook", "WebhookNotificationChannel"),
        ):
            config = _config(tmp_path, inspection_notifications=InspectionNotificationsConfig(**{flag: True}))
            with pytest.raises(ValueError) as exc_info:
                build_paper_trading_context(
                    config=config, clock=FixedClock(_now()),
                    id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
                )
            assert class_name in str(exc_info.value)


class TestSlackChannelWiring:
    """Etapa 6.13 (§28): SlackNotificationChannel deja de ser
    placeholder -- se construye e inyecta como canal real cuando
    inspection_notifications.slack=True y el webhook es válido."""

    _VALID_WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXX"

    def test_disabled_by_default_slack_not_constructed(self, tmp_path):
        from src.paper_trading.notification_channels import SlackNotificationChannel

        config = _config(tmp_path)  # default: slack=False
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert not any(isinstance(c, SlackNotificationChannel) for c in channels)

    def test_disabled_by_default_does_not_require_webhook(self, tmp_path):
        from src.utils.config import SlackSettings

        config = _config(tmp_path, slack=SlackSettings(webhook_url=None))
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context is not None

    def test_disabled_preserves_previous_behavior(self, tmp_path):
        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        from src.paper_trading.notification_channels import LoggingNotificationChannel

        channels = context.alert_delivery_service._channel._channels
        assert len(channels) == 1
        assert isinstance(channels[0], LoggingNotificationChannel)

    def test_enabled_and_configured_builds_slack_channel(self, tmp_path):
        from src.paper_trading.notification_channels import SlackNotificationChannel
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=self._VALID_WEBHOOK, timeout_seconds=7.5),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        slack_channels = [c for c in channels if isinstance(c, SlackNotificationChannel)]
        assert len(slack_channels) == 1

    def test_channel_does_not_retain_the_webhook(self, tmp_path):
        from src.paper_trading.notification_channels import SlackNotificationChannel
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=self._VALID_WEBHOOK),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        slack_channel = next(c for c in channels if isinstance(c, SlackNotificationChannel))
        assert set(vars(slack_channel).keys()) == {"_transport", "_clock"}
        assert "XXXX" not in repr(slack_channel)
        assert "XXXX" not in repr(slack_channel._transport)

    def test_transport_receives_the_correct_configuration(self, tmp_path, monkeypatch):
        """Confirma la configuración correcta sin inspeccionar
        directamente el atributo sensible en el objeto ya construido:
        se intercepta la llamada al constructor del transporte (spy)."""
        import src.paper_trading.composition as composition_module
        from src.paper_trading.slack_transport import UrllibSlackTransport
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        captured = {}
        real_transport_cls = UrllibSlackTransport

        def _spy_transport(*, config, timeout_seconds=10.0):
            captured["webhook_matches_expected"] = (config.webhook_url == self._VALID_WEBHOOK)
            captured["timeout_seconds"] = timeout_seconds
            return real_transport_cls(config=config, timeout_seconds=timeout_seconds)

        monkeypatch.setattr(composition_module, "UrllibSlackTransport", _spy_transport)

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=self._VALID_WEBHOOK, timeout_seconds=6.5),
        )
        build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert captured["webhook_matches_expected"] is True
        assert captured["timeout_seconds"] == 6.5

    def test_channel_order_is_logging_telegram_slack(self, tmp_path):
        from src.paper_trading.notification_channels import (
            LoggingNotificationChannel, SlackNotificationChannel, TelegramNotificationChannel,
        )
        from src.utils.config import InspectionNotificationsConfig, SlackSettings, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(logging=True, telegram=True, slack=True),
            telegram=TelegramSettings(bot_token="tok", chat_id="chat"),
            slack=SlackSettings(webhook_url=self._VALID_WEBHOOK),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert [type(c) for c in channels] == [
            LoggingNotificationChannel, TelegramNotificationChannel, SlackNotificationChannel,
        ]

    def test_slack_is_no_longer_a_placeholder(self, tmp_path):
        """Confirma que habilitar Slack ya no dispara el ValueError de
        placeholder bloqueado (§25.3) -- construye el contexto con éxito."""
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=self._VALID_WEBHOOK),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context is not None

    def test_enabled_without_webhook_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=None),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "webhook" in str(exc_info.value).lower()

    def test_enabled_with_empty_webhook_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=""),
        )
        with pytest.raises(ValueError):
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )

    def test_enabled_with_http_scheme_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url="http://hooks.slack.com/services/T000/B000/XXXX"),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "https" in str(exc_info.value).lower()

    def test_enabled_with_wrong_host_fails_to_build_context(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url="https://evilslack.com/services/T000/B000/XXXX"),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "host" in str(exc_info.value).lower()

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.5, math.nan, math.inf, -math.inf])
    def test_enabled_with_invalid_timeout_fails_to_build_context(self, tmp_path, bad_timeout):
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=self._VALID_WEBHOOK, timeout_seconds=bad_timeout),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "timeout" in str(exc_info.value).lower()

    def test_slack_error_never_includes_the_webhook(self, tmp_path):
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url="https://evilslack.com/services/T000/B000/SECRETPATH"),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "SECRETPATH" not in str(exc_info.value)
        assert "evilslack.com" not in str(exc_info.value)


class TestSlackChannelWiringHardenedValidation:
    """Etapa 6.13.1 (§28.x, punto 21): una URL de webhook inválida
    (userinfo/query/fragment/puerto no permitido/ruta inválida) debe
    fallar de inmediato al construir el contexto, sin construir el
    canal ni realizar ninguna conexión, y sin exponer el webhook."""

    def _assert_fails_without_building_channel(self, tmp_path, webhook_url):
        from src.paper_trading.notification_channels import SlackNotificationChannel
        from src.utils.config import InspectionNotificationsConfig, SlackSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(slack=True),
            slack=SlackSettings(webhook_url=webhook_url),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert webhook_url not in str(exc_info.value)
        return exc_info

    def test_userinfo_fails_to_build_context(self, tmp_path):
        self._assert_fails_without_building_channel(
            tmp_path, "https://secretuser@hooks.slack.com/services/T/B/X",
        )

    def test_query_string_fails_to_build_context(self, tmp_path):
        exc_info = self._assert_fails_without_building_channel(
            tmp_path, "https://hooks.slack.com/services/T/B/X?token=secret",
        )
        assert "token=secret" not in str(exc_info.value)

    def test_fragment_fails_to_build_context(self, tmp_path):
        exc_info = self._assert_fails_without_building_channel(
            tmp_path, "https://hooks.slack.com/services/T/B/X#secret",
        )
        assert "secret" not in str(exc_info.value)

    def test_port_8443_fails_to_build_context(self, tmp_path):
        self._assert_fails_without_building_channel(
            tmp_path, "https://hooks.slack.com:8443/services/T/B/X",
        )

    def test_invalid_path_fails_to_build_context(self, tmp_path):
        self._assert_fails_without_building_channel(
            tmp_path, "https://hooks.slack.com/services/T/B",
        )


class TestEmailChannelWiring:
    """Etapa 6.14 (§29): EmailNotificationChannel deja de ser
    placeholder -- se construye e inyecta como canal real cuando
    inspection_notifications.email=True y la configuración SMTP es
    válida."""

    _VALID_HOST = "smtp.example.com"
    _VALID_SENDER = "alerts@example.com"
    _VALID_RECIPIENT = "ops@example.com"

    def test_disabled_by_default_email_not_constructed(self, tmp_path):
        from src.paper_trading.notification_channels import EmailNotificationChannel

        config = _config(tmp_path)  # default: email=False
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert not any(isinstance(c, EmailNotificationChannel) for c in channels)

    def test_disabled_by_default_does_not_require_smtp_settings(self, tmp_path):
        from src.utils.config import EmailSettings

        config = _config(tmp_path, email=EmailSettings(host=None, sender=None, recipient=None))
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context is not None

    def test_disabled_preserves_previous_behavior(self, tmp_path):
        config = _config(tmp_path)
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        from src.paper_trading.notification_channels import LoggingNotificationChannel

        channels = context.alert_delivery_service._channel._channels
        assert len(channels) == 1
        assert isinstance(channels[0], LoggingNotificationChannel)

    def test_enabled_and_configured_builds_email_channel(self, tmp_path):
        from src.paper_trading.notification_channels import EmailNotificationChannel
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, port=587, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                security="starttls", timeout_seconds=7.5,
            ),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        email_channels = [c for c in channels if isinstance(c, EmailNotificationChannel)]
        assert len(email_channels) == 1

    def test_channel_does_not_retain_credentials(self, tmp_path):
        from src.paper_trading.notification_channels import EmailNotificationChannel
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                username="secretuser", password="SECRETPW123",
            ),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        email_channel = next(c for c in channels if isinstance(c, EmailNotificationChannel))
        assert set(vars(email_channel).keys()) == {"_transport", "_clock"}
        assert "SECRETPW123" not in repr(email_channel)
        assert "SECRETPW123" not in repr(email_channel._transport)

    def test_transport_receives_the_correct_configuration(self, tmp_path, monkeypatch):
        """Confirma la configuración correcta sin inspeccionar
        directamente el atributo sensible en el objeto ya construido:
        se intercepta la llamada al constructor del transporte (spy)."""
        import src.paper_trading.composition as composition_module
        from src.paper_trading.email_transport import SmtpEmailTransport
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        captured = {}
        real_transport_cls = SmtpEmailTransport

        def _spy_transport(*, config, timeout_seconds=10.0):
            captured["host_matches_expected"] = (config.host == self._VALID_HOST)
            captured["sender_matches_expected"] = (config.sender == self._VALID_SENDER)
            captured["timeout_seconds"] = timeout_seconds
            return real_transport_cls(config=config, timeout_seconds=timeout_seconds)

        monkeypatch.setattr(composition_module, "SmtpEmailTransport", _spy_transport)

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                timeout_seconds=6.5,
            ),
        )
        build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert captured["host_matches_expected"] is True
        assert captured["sender_matches_expected"] is True
        assert captured["timeout_seconds"] == 6.5

    def test_channel_order_is_logging_telegram_slack_email(self, tmp_path):
        from src.paper_trading.notification_channels import (
            EmailNotificationChannel, LoggingNotificationChannel, SlackNotificationChannel,
            TelegramNotificationChannel,
        )
        from src.utils.config import EmailSettings, InspectionNotificationsConfig, SlackSettings, TelegramSettings

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(
                logging=True, telegram=True, slack=True, email=True,
            ),
            telegram=TelegramSettings(bot_token="tok", chat_id="chat"),
            slack=SlackSettings(webhook_url="https://hooks.slack.com/services/T000/B000/XXXX"),
            email=EmailSettings(host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        channels = context.alert_delivery_service._channel._channels
        assert [type(c) for c in channels] == [
            LoggingNotificationChannel, TelegramNotificationChannel, SlackNotificationChannel, EmailNotificationChannel,
        ]

    def test_email_is_no_longer_a_placeholder(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT),
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert context is not None

    def test_enabled_without_host_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(host=None, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "host" in str(exc_info.value).lower()

    def test_enabled_with_invalid_port_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, port=0, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "port" in str(exc_info.value).lower()

    def test_enabled_without_sender_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(host=self._VALID_HOST, sender=None, recipient=self._VALID_RECIPIENT),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "sender" in str(exc_info.value).lower()

    def test_enabled_without_recipient_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=None),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "recipient" in str(exc_info.value).lower()

    def test_enabled_with_invalid_security_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                security="none",
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "security" in str(exc_info.value).lower()

    def test_enabled_with_username_without_password_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                username="user", password=None,
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "password" in str(exc_info.value).lower()

    def test_enabled_with_password_without_username_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                username=None, password="pw",
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "password" in str(exc_info.value).lower()

    def test_enabled_with_header_injection_in_address_fails_to_build_context(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        malicious = "a@example.com\nBcc: victim@evil.com"
        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(host=self._VALID_HOST, sender=malicious, recipient=self._VALID_RECIPIENT),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "victim@evil.com" not in str(exc_info.value)

    def test_email_error_never_includes_the_username(self, tmp_path):
        from src.utils.config import EmailSettings, InspectionNotificationsConfig

        config = _config(
            tmp_path,
            inspection_notifications=InspectionNotificationsConfig(email=True),
            email=EmailSettings(
                host=self._VALID_HOST, sender=self._VALID_SENDER, recipient=self._VALID_RECIPIENT,
                username="MY-SECRET-USER", password=None,
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            build_paper_trading_context(
                config=config, clock=FixedClock(_now()),
                id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
            )
        assert "MY-SECRET-USER" not in str(exc_info.value)


class TestNotificationTemplateWiring:
    """Etapa 6.11 (§26): la Composition Root construye e inyecta el
    InspectionNotificationTemplate en AlertDeliveryService -- nunca lo
    construye AlertDeliveryService por sí solo."""

    def test_alert_delivery_service_receives_the_default_template(self, tmp_path):
        from src.paper_trading.notification_templates import DefaultInspectionNotificationTemplate

        context = build_paper_trading_context(
            config=_config(tmp_path), clock=FixedClock(_now()),
            id_generator=DeterministicIdGenerator(), market_price_provider=FakePriceProvider(),
        )
        assert isinstance(context.alert_delivery_service._template, DefaultInspectionNotificationTemplate)

    def test_composition_root_constructs_the_template(self):
        import src.paper_trading.composition as module

        source = open(module.__file__, encoding="utf-8").read()
        assert "DefaultInspectionNotificationTemplate(" in source
