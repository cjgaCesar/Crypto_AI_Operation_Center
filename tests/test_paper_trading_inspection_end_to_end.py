"""
Prueba integral de punta a punta de la automatización de inspecciones
(Etapa 6.9, Paso 42): detectar -> alertar -> deduplicar tras reinicio ->
reparar manualmente (Etapa 6.8, fuera del scheduler) -> detectar la
resolución -> entregar. Confirma que el job nunca llama repair() y que
los datos operacionales solo cambian por el repair manual.
"""

from datetime import datetime, timezone
from decimal import Decimal

from src.paper_trading.alert_delivery_service import AlertDeliveryService
from src.paper_trading.alert_sink import NullInspectionAlertSink
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType
from src.paper_trading.inspection_service import InspectionService
from src.paper_trading.models import CashBalance, Order
from src.paper_trading.reconciliation_service import ReconciliationService
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


class FixedClock:
    def __init__(self, fixed: datetime):
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed


class DeterministicIdGenerator:
    """`start` simula que un reinicio real (UUIDIdGenerator) nunca repite
    un id ya usado -- a diferencia de un contador ingenuo reiniciado en 0."""

    def __init__(self, start: int = 0):
        self._n = start

    def _next(self, prefix):
        self._n += 1
        return f"{prefix}-{self._n}"

    def new_inspection_run_id(self) -> str:
        return self._next("run")

    def new_inspection_alert_id(self) -> str:
        return self._next("alert")

    def new_reconciliation_audit_id(self) -> str:
        return self._next("audit")


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pending_buy_order() -> Order:
    return Order(
        id="order-1", exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.PENDING, source=OrderSource.MANUAL,
        created_at=_now(), updated_at=_now(), reserved_price=Decimal("50000"),
        reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
    )


def _build_inspection_service(repo, id_start: int = 0) -> InspectionService:
    return InspectionService(
        repository=repo, reconciliation_service=ReconciliationService(repo),
        id_generator=DeterministicIdGenerator(start=id_start), clock=FixedClock(_now()),
    )


def _build_delivery_service(repo) -> AlertDeliveryService:
    return AlertDeliveryService(repo, NullInspectionAlertSink(clock=FixedClock(_now())), max_attempts=3)


class TestEndToEndInspectionAutomation:
    def test_full_lifecycle_detect_alert_deduplicate_repair_resolve(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        # 1-2. SQLite temporal + capital inicial.
        repo = SQLitePaperTradingRepository(db_path)
        repo.init()
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("5005"), updated_at=_now(),
        ))
        repo.save_order(_pending_buy_order())

        # 3-4. Primera inspección, estado consistente, persistida.
        inspection_service = _build_inspection_service(repo)
        run1 = inspection_service.run_inspection(run_id="run-1", started_at=_now())
        assert run1.success is True
        assert run1.report.is_consistent is True

        # 5. Cero alertas relevantes (estado ya consistente: sin issues en absoluto).
        assert run1.alert_count == 0
        assert repo.fetch_pending_inspection_alerts() == []

        # 6. Introducir inconsistencia controlada directamente en la persistencia de prueba.
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("999"), updated_at=_now(),
        ))

        # 7. Segunda inspección.
        run2 = inspection_service.run_inspection(run_id="run-2", started_at=_now())

        # 8. Confirmar NEW_ISSUE.
        assert run2.new_issue_count == 1
        codes = {issue.code.value for issue in run2.report.issues}
        assert "CASH_RESERVED_BALANCE_MISMATCH" in codes

        # 9. Confirmar alerta PENDING.
        pending_alerts = repo.fetch_pending_inspection_alerts()
        assert len(pending_alerts) == 1
        assert pending_alerts[0].alert_type.value == "NEW_ISSUE"
        dedup_key = pending_alerts[0].deduplication_key

        # 10-11. Entregar con NullInspectionAlertSink; confirmar DELIVERED.
        delivery_service = _build_delivery_service(repo)
        delivery_result = delivery_service.deliver_pending_alerts()
        assert delivery_result.delivered_count == 1
        assert repo.get_inspection_alert_by_deduplication_key(dedup_key).status.value == "DELIVERED"

        # 12. "Reiniciar" la Composition Root: nueva instancia de repositorio/servicio sobre el mismo archivo.
        restarted_repo = SQLitePaperTradingRepository(db_path)
        restarted_repo.init()
        restarted_inspection_service = _build_inspection_service(restarted_repo, id_start=100)

        # 13. Tercera inspección, misma inconsistencia todavía presente.
        run3 = restarted_inspection_service.run_inspection(run_id="run-3", started_at=_now())

        # 14. No duplica la alerta ya entregada (misma identidad+severidad -> misma dedup_key).
        assert run3.new_issue_count == 0
        assert run3.persistent_issue_count == 1
        assert run3.alert_count == 0
        assert restarted_repo.get_inspection_alert_by_deduplication_key(dedup_key).status.value == "DELIVERED"

        # 15. Reparación manual de la Etapa 6.8, fuera del scheduler/job por completo.
        reconciliation_service = ReconciliationService(restarted_repo)
        repair_result = reconciliation_service.repair(audit_id="audit-1", timestamp=_now(), dry_run=False)
        assert repair_result.success is True
        assert restarted_repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")

        # 16-17. Cuarta inspección: RESOLVED_ISSUE.
        run4 = restarted_inspection_service.run_inspection(run_id="run-4", started_at=_now())
        assert run4.resolved_issue_count == 1
        assert run4.report.is_consistent is True

        resolved_alerts = [
            alert for alert in restarted_repo.fetch_pending_inspection_alerts()
            if alert.alert_type.value == "RESOLVED_ISSUE"
        ]
        assert len(resolved_alerts) == 1

        # 18. Entregar la alerta de resolución.
        restarted_delivery_service = _build_delivery_service(restarted_repo)
        final_delivery = restarted_delivery_service.deliver_pending_alerts()
        assert final_delivery.delivered_count == 1

        # 19. Confirmar historial completo (4 corridas).
        history = restarted_repo.fetch_inspection_runs(limit=None)
        assert {run.id for run in history} == {"run-1", "run-2", "run-3", "run-4"}

        # 20. El job/servicio de inspección nunca llamó repair(): confirmado
        # estructuralmente (InspectionService no tiene ningún atributo ni
        # importación relacionada a repair).
        import src.paper_trading.inspection_service as inspection_service_module
        source = open(inspection_service_module.__file__, encoding="utf-8").read()
        assert ".repair(" not in source

        # 21. Los datos operacionales solo cambiaron por el repair manual:
        # antes del repair, reserved_balance seguía en 999 (las 2 inspecciones
        # automáticas no lo tocaron); después del repair, quedó en 5005.
        assert restarted_repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")
        assert restarted_repo.get_order("order-1").status == OrderStatus.PENDING
        assert restarted_repo.fetch_executions(limit=None) == []
        assert restarted_repo.fetch_trades(limit=None) == []
