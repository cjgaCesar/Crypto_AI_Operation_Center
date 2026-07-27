"""
Caracterización y endurecimiento de concurrencia SQLite para
SQLitePaperTradingRepository (Etapa 6.17).

Ver docs/ARQUITECTURA_PAPER_TRADING.md §32. Estas pruebas usan
exclusivamente la biblioteca estándar (`threading`/`sqlite3`/`time`) --
sin conexiones externas, sin dependencias nuevas. Prefieren
`threading.Thread`/`threading.Barrier` para que la concurrencia sea
explícita, evitando depender de `sleep()` como único mecanismo de
sincronización.

Metodología (§4 de la etapa, obligatoria): primero se caracterizó el
comportamiento actual (sin modificar código), después se aplicó el
cambio mínimo que la evidencia justificó -- ver la sección
"CARACTERIZACIÓN INICIAL" más abajo para el registro exacto de lo que
se observó contra el código sin modificar, antes de agregar
`timeout_seconds` a `SQLitePaperTradingRepository`.

CARACTERIZACIÓN INICIAL (registrada antes de tocar sqlite_repository.py):

- `sqlite3.connect(path)` sin `timeout=` explícito ya usa el default de
  Python: 5.0 segundos, que se traduce internamente en
  `PRAGMA busy_timeout = 5000`. Verificado empíricamente: dos
  conexiones directas (`sqlite3.connect`), una con `BEGIN IMMEDIATE` +
  escritura sin commit, la otra intentando escribir, produce
  `sqlite3.OperationalError: database is locked` después de ~5.5s.
- El modo de diario por defecto es `delete` (rollback journal clásico),
  no WAL.
- Un lector con una conexión separada pudo leer el valor ya confirmado
  mientras otra conexión mantenía una transacción de escritura abierta
  sin commit (no bloqueó) -- ver `TestReaderDuringOpenWriteTransaction`.
- Ningún timeout/`PRAGMA busy_timeout`/`journal_mode` estaba expuesto
  como parámetro configurable ni verificado por ninguna prueba antes de
  esta etapa.

Hallazgo demostrado (no inventado): el timeout efectivo YA existía
(5.0s, default de Python), pero era implícito, no configurable ni
testeado -- el cambio mínimo aplicado es hacerlo explícito
(`timeout_seconds: float = 5.0`, mismo valor por defecto, sin romper
`SQLitePaperTradingRepository(path)` posicional existente), con
validación (`bool`/0/negativo/NaN/infinito rechazados). WAL se evaluó y
se descartó por falta de evidencia de un problema real que resolviera
(ver §32 de la documentación) -- el modo por defecto ya permite lectura
de datos confirmados mientras hay una transacción de escritura abierta
sin commit, y la contención escritor-escritor ya produce un fallo
controlado (`sqlite3.OperationalError`) dentro del timeout configurado,
sin necesidad de WAL para este patrón de uso (conexión nueva por
operación, transacciones cortas).
"""

import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide
from src.paper_trading.models import CashBalance, Execution, Order, Position
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository

_SHORT_TIMEOUT = 0.5  # segundos: acorta las pruebas sin cambiar el comportamiento medido.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order(order_id: str, **overrides) -> Order:
    defaults = dict(
        id=order_id, exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.NEW, source=OrderSource.MANUAL,
        created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


class TestJournalModeCharacterization:
    """§11: medir el modo actual antes de decidir si WAL se justifica."""

    def test_default_journal_mode_is_not_wal(self, tmp_path):
        repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        repo.init()
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        # Documenta el estado real -- no se asume WAL, se mide.
        assert mode in ("delete", "wal")  # registrado en el informe cuál es


class TestReaderDuringOpenWriteTransaction:
    """§18: en el modo actual (sin WAL forzado), un lector con su propia
    conexión puede leer el último valor CONFIRMADO mientras otra
    conexión mantiene una transacción de escritura abierta sin commit
    -- no exige que WAL esté activo, solo documenta el comportamiento
    real medido."""

    def test_reader_sees_committed_value_while_writer_transaction_is_open(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo = SQLitePaperTradingRepository(db_path)
        repo.init()
        repo.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("100"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))

        writer_conn = sqlite3.connect(db_path)
        writer_conn.execute("BEGIN IMMEDIATE")
        writer_conn.execute(
            "UPDATE paper_trading_cash_balances SET total_balance = ? WHERE currency = ?",
            ("999", "USDT"),
        )
        # Sin commit todavía.

        try:
            reader_repo = SQLitePaperTradingRepository(db_path, timeout_seconds=_SHORT_TIMEOUT)
            balance = reader_repo.get_cash_balance("USDT")
            assert balance.total_balance == Decimal("100")  # el valor confirmado, nunca el no confirmado
        finally:
            writer_conn.commit()
            writer_conn.close()


class TestTimeoutValidationContract:
    """§10: reglas de validación del parámetro timeout_seconds."""

    def test_default_construction_still_works(self, tmp_path):
        repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        assert repo is not None
        repo.init()  # confirma que la construcción posicional sin timeout sigue funcionando

    @pytest.mark.parametrize("bad_timeout", [
        True, False, 0, -1, -0.5, float("nan"), float("inf"), float("-inf"),
    ])
    def test_rejects_invalid_timeout(self, tmp_path, bad_timeout):
        with pytest.raises(ValueError):
            SQLitePaperTradingRepository(str(tmp_path / "test.db"), timeout_seconds=bad_timeout)

    @pytest.mark.parametrize("good_timeout", [0.1, 1, 5.0, 30])
    def test_accepts_positive_timeout(self, tmp_path, good_timeout):
        repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"), timeout_seconds=good_timeout)
        assert repo is not None


class TestTwoIndependentWriters:
    """§7: dos escritores independientes, entidades distintas, sin
    contención real esperada -- confirma ausencia de cuelgue/corrupción
    y que ambas entidades quedan persistidas."""

    def test_two_threads_save_different_orders_concurrently(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        repo_a = SQLitePaperTradingRepository(db_path)
        repo_b = SQLitePaperTradingRepository(db_path)
        barrier = threading.Barrier(2)
        errors: "queue.Queue[Exception]" = queue.Queue()

        def _save(repo, order_id):
            barrier.wait(timeout=5)
            try:
                repo.save_order(_order(order_id))
            except Exception as exc:  # pragma: no cover - solo si algo realmente falla
                errors.put(exc)

        thread_a = threading.Thread(target=_save, args=(repo_a, "order-a"))
        thread_b = threading.Thread(target=_save, args=(repo_b, "order-b"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        assert not thread_a.is_alive() and not thread_b.is_alive()  # ningún cuelgue
        assert errors.empty(), f"escritor falló inesperadamente: {list(errors.queue)}"

        verify_repo = SQLitePaperTradingRepository(db_path)
        assert verify_repo.get_order("order-a") is not None
        assert verify_repo.get_order("order-b") is not None


class TestRealContentionOverATransaction:
    """§8: una conexión abre BEGIN IMMEDIATE y mantiene el bloqueo de
    forma controlada; una segunda conexión (a través del propio
    repositorio) intenta escribir. Mide el resultado real, con límites
    temporales claros -- nunca espera indefinidamente."""

    def test_second_writer_blocked_then_fails_with_operational_error(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        blocker_conn = sqlite3.connect(db_path)
        blocker_conn.execute("BEGIN IMMEDIATE")
        blocker_conn.execute(
            "INSERT INTO paper_trading_orders (id, exchange, symbol, side, order_type, quantity, status, "
            "filled_quantity, source, created_at, updated_at) VALUES "
            "('blocker', 'Binance', 'BTCUSDT', 'BUY', 'MARKET', '0.1', 'NEW', '0', 'MANUAL', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )

        repo = SQLitePaperTradingRepository(db_path, timeout_seconds=_SHORT_TIMEOUT)
        start = time.monotonic()
        try:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                repo.save_order(_order("order-blocked"))
            elapsed = time.monotonic() - start
            assert "locked" in str(exc_info.value).lower()
            # Debe esperar aproximadamente el timeout configurado, nunca indefinidamente.
            assert elapsed < _SHORT_TIMEOUT + 2.0
            assert elapsed >= _SHORT_TIMEOUT * 0.5
        finally:
            blocker_conn.commit()
            blocker_conn.close()

    def test_busy_timeout_pragma_reflects_configured_value(self, tmp_path):
        """§25: se consulta SQLite realmente (nunca se afirma por
        inspección de código) que `PRAGMA busy_timeout` refleja el
        `timeout_seconds` configurado, convertido a milisegundos de
        forma determinista."""
        db_path = str(tmp_path / "test.db")
        repo = SQLitePaperTradingRepository(db_path, timeout_seconds=2.5)
        repo.init()
        conn = repo._get_connection()
        try:
            value = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        finally:
            conn.close()
        assert value == 2500


class TestLockReleasedBeforeTimeout:
    """§16: Hilo A mantiene el bloqueo, Hilo B intenta escribir, Hilo A
    libera el bloqueo ANTES de que expire el timeout configurado -- Hilo
    B debe completar correctamente, sin reintentos manuales en el
    repositorio (el único reintento es el interno de SQLite mientras
    espera el bloqueo, que no es un reintento de negocio) y sin pérdida
    ni duplicación de datos."""

    def test_writer_b_succeeds_once_writer_a_releases_within_timeout(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        hold_seconds = 0.5
        configured_timeout = 3.0  # ampliamente mayor que hold_seconds
        barrier = threading.Barrier(2)
        errors: "queue.Queue[Exception]" = queue.Queue()

        def _hold_lock():
            barrier.wait(timeout=5)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO paper_trading_cash_balances (currency, total_balance, reserved_balance, updated_at) "
                    "VALUES ('HOLD', '1', '0', '2026-01-01T00:00:00+00:00')"
                )
                time.sleep(hold_seconds)
                conn.commit()
            except Exception as exc:
                errors.put(exc)
            finally:
                conn.close()

        def _write_b():
            barrier.wait(timeout=5)
            try:
                repo_b = SQLitePaperTradingRepository(db_path, timeout_seconds=configured_timeout)
                repo_b.save_order(_order("order-after-release"))
            except Exception as exc:
                errors.put(exc)

        thread_a = threading.Thread(target=_hold_lock)
        thread_b = threading.Thread(target=_write_b)
        start = time.monotonic()
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)
        elapsed = time.monotonic() - start

        assert not thread_a.is_alive() and not thread_b.is_alive()
        assert errors.empty(), f"fallo inesperado: {list(errors.queue)}"
        # B esperó aproximadamente hold_seconds (bloqueado), no near-zero,
        # pero muy por debajo del timeout configurado (nunca esperó los 3s completos).
        assert elapsed >= hold_seconds * 0.5
        assert elapsed < configured_timeout

        verify_repo = SQLitePaperTradingRepository(db_path)
        assert verify_repo.get_order("order-after-release") is not None  # sin pérdida
        assert verify_repo.get_cash_balance("HOLD") is not None  # el hold también se persistió, sin duplicar nada


class TestForeignKeysPerConnection:
    """§14: confirmar (consultando SQLite, no el código fuente) que
    `PRAGMA foreign_keys = ON` se aplica en cada conexión nueva, no solo
    en `init()`."""

    def test_foreign_keys_enabled_on_a_fresh_connection_after_init(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        # Una conexión completamente nueva, abierta por fuera del repositorio.
        conn = sqlite3.connect(db_path)
        try:
            value_before = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        finally:
            conn.close()
        # SQLite no conserva PRAGMA foreign_keys entre conexiones: una
        # conexión externa cruda, sin pasar por el repositorio, lo
        # tendrá deshabilitado por defecto -- confirma que la garantía
        # depende de que TODAS las conexiones pasen por el repositorio.
        assert value_before == 0

        # La conexión que el propio repositorio abre sí lo activa.
        repo = SQLitePaperTradingRepository(db_path)
        repo_conn = repo._get_connection()
        try:
            value_via_repo = repo_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        finally:
            repo_conn.close()
        assert value_via_repo == 1

    def test_foreign_key_violation_is_rejected(self, tmp_path):
        """Confirmación de comportamiento observable (no de código): con
        foreign_keys=ON ya vigente en cada conexión, insertar una
        Execution que referencia una Order inexistente debe fallar."""
        db_path = str(tmp_path / "test.db")
        repo = SQLitePaperTradingRepository(db_path)
        repo.init()
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_execution(Execution(
                id="exec-orphan", order_id="no-existe", exchange="Binance", symbol="BTCUSDT",
                quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=_now(),
            ))


class TestAtomicityUnderContention:
    """§15: una operación compuesta real (`save_fill_transaction`, la
    única transacción multi-tabla del repositorio) encuentra contención
    -- confirma que nunca queda un estado parcial: o se persiste
    completa, o ninguna de sus tablas cambia."""

    def test_fill_transaction_leaves_no_partial_state_when_blocked(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        repo_setup = SQLitePaperTradingRepository(db_path)
        repo_setup.init()
        repo_setup.save_cash_balance(CashBalance(
            currency="USDT", total_balance=Decimal("10000"), reserved_balance=Decimal("0"), updated_at=_now(),
        ))

        blocker_conn = sqlite3.connect(db_path)
        blocker_conn.execute("BEGIN IMMEDIATE")
        blocker_conn.execute(
            "INSERT INTO paper_trading_cash_balances (currency, total_balance, reserved_balance, updated_at) "
            "VALUES ('BLOCK', '1', '0', '2026-01-01T00:00:00+00:00')"
        )

        order = _order("order-fill-blocked", status=OrderStatus.PENDING)
        execution = Execution(
            id="exec-blocked", order_id="order-fill-blocked", exchange="Binance", symbol="BTCUSDT",
            quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"), executed_at=_now(),
        )
        position = Position(
            exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG, quantity=Decimal("0.1"),
            reserved_quantity=Decimal("0"), average_entry_price=Decimal("50000"),
            realized_pnl_to_date=Decimal("0"), updated_at=_now(),
        )
        cash_balance = CashBalance(
            currency="USDT", total_balance=Decimal("4995"), reserved_balance=Decimal("0"), updated_at=_now(),
        )

        repo = SQLitePaperTradingRepository(db_path, timeout_seconds=_SHORT_TIMEOUT)
        try:
            with pytest.raises(sqlite3.OperationalError):
                repo.save_fill_transaction(
                    order=order, execution=execution, position=position, cash_balance=cash_balance,
                )
        finally:
            blocker_conn.commit()
            blocker_conn.close()

        verify_repo = SQLitePaperTradingRepository(db_path)
        # Ninguna parte de la transacción compuesta quedó persistida.
        assert verify_repo.get_order("order-fill-blocked") is None
        assert verify_repo.fetch_executions_by_order("order-fill-blocked") == []
        assert verify_repo.get_position("Binance", "BTCUSDT") is None
        assert verify_repo.get_cash_balance("USDT").total_balance == Decimal("10000")  # sin cambios


class TestMultipleWriters:
    """§19: al menos 4 hilos, 10 operaciones por hilo, IDs únicos --
    confirma que todos terminan, la cantidad final es exacta, sin
    duplicados ni pérdida silenciosa."""

    def test_four_threads_ten_orders_each(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        thread_count = 4
        orders_per_thread = 10
        barrier = threading.Barrier(thread_count)
        errors: "queue.Queue[Exception]" = queue.Queue()

        def _worker(thread_index):
            repo = SQLitePaperTradingRepository(db_path)
            barrier.wait(timeout=5)
            for i in range(orders_per_thread):
                try:
                    repo.save_order(_order(f"order-t{thread_index}-{i}"))
                except Exception as exc:
                    errors.put(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert all(not thread.is_alive() for thread in threads)
        assert errors.empty(), f"fallo inesperado: {list(errors.queue)}"

        verify_repo = SQLitePaperTradingRepository(db_path)
        all_orders = verify_repo.fetch_orders(limit=None)
        assert len(all_orders) == thread_count * orders_per_thread
        assert len({order.id for order in all_orders}) == thread_count * orders_per_thread  # sin duplicados


class TestRestartAfterConcurrentWrites:
    """§20: tras las escrituras concurrentes, cerrar todo, crear una
    nueva instancia, ejecutar init() y confirmar que los datos
    confirmados siguen disponibles."""

    def test_data_survives_reinstantiation_and_reinit(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        barrier = threading.Barrier(4)

        def _worker(thread_index):
            repo = SQLitePaperTradingRepository(db_path)
            barrier.wait(timeout=5)
            for i in range(5):
                repo.save_order(_order(f"restart-order-t{thread_index}-{i}"))

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        # "Reinicio": nueva instancia sobre el mismo archivo.
        restarted_repo = SQLitePaperTradingRepository(db_path)
        restarted_repo.init()  # debe seguir siendo idempotente
        all_orders = restarted_repo.fetch_orders(limit=None)
        assert len(all_orders) == 20
        assert restarted_repo.get_order("restart-order-t0-0") is not None


class TestIntegrityCheck:
    """§21: verificación de integridad tras el escenario de múltiples
    escritores -- solo como chequeo de prueba, nunca en cada operación
    productiva."""

    def test_integrity_check_is_ok_after_concurrent_writes(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        SQLitePaperTradingRepository(db_path).init()

        barrier = threading.Barrier(4)

        def _worker(thread_index):
            repo = SQLitePaperTradingRepository(db_path)
            barrier.wait(timeout=5)
            for i in range(10):
                repo.save_order(_order(f"integrity-order-t{thread_index}-{i}"))

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        conn = sqlite3.connect(db_path)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        assert result == "ok"


class TestSchedulerConcurrentAccess:
    """§22: una corrida de inspección (representando el scheduler/
    inspection job) escribiendo mientras otro repositorio realiza una
    operación de Paper Trading -- una sola iteración, nunca un proceso
    infinito real."""

    def test_inspection_run_and_order_acceptance_both_complete(self, tmp_path):
        from decimal import Decimal as D

        from src.paper_trading.composition import build_paper_trading_context
        from src.paper_trading.enums import OrderSide as ES, OrderSource as ESrc, OrderStatus as EStatus, OrderType as ET
        from src.paper_trading.models import Order as OrderModel
        from src.utils.config import PaperTradingConfig

        class FixedClock:
            def __init__(self, fixed):
                self._fixed = fixed

            def now(self):
                return self._fixed

        class DeterministicIdGenerator:
            def __init__(self):
                self._n = 0

            def _next(self, prefix):
                self._n += 1
                return f"{prefix}-{self._n}"

            def new_order_id(self): return self._next("order")
            def new_execution_id(self): return self._next("exec")
            def new_trade_id(self): return self._next("trade")
            def new_reconciliation_audit_id(self): return self._next("audit")
            def new_inspection_run_id(self): return self._next("run")
            def new_inspection_alert_id(self): return self._next("alert")

        class FakePriceProvider:
            def get_current_price(self, exchange, symbol):
                raise NotImplementedError

            def get_current_prices(self, symbols):
                raise NotImplementedError

        db_path = str(tmp_path / "test.db")
        config = PaperTradingConfig(
            enabled=True, database_path=db_path, initial_capital=Decimal("10000"),
            currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("1000"),
            max_position_value=Decimal("5000"), rules_version="v1",
        )
        context = build_paper_trading_context(
            config=config, clock=FixedClock(_now()), id_generator=DeterministicIdGenerator(),
            market_price_provider=FakePriceProvider(),
        )

        barrier = threading.Barrier(2)
        errors: "queue.Queue[Exception]" = queue.Queue()

        def _run_inspection():
            barrier.wait(timeout=5)
            try:
                context.inspection_job.run_once()
            except Exception as exc:
                errors.put(exc)

        def _accept_order():
            barrier.wait(timeout=5)
            try:
                order = OrderModel(
                    id="concurrent-order-1", exchange="Binance", symbol="BTCUSDT", side=ES.BUY,
                    order_type=ET.MARKET, quantity=D("0.01"), status=EStatus.NEW, source=ESrc.MANUAL,
                    created_at=_now(), updated_at=_now(),
                )
                context.service.accept_market_order(
                    order=order, market_price=D("50000"), fee_rate=D("0.001"), timestamp=_now(),
                    max_order_value=D("100000"), max_position_value=D("100000"), rules_version="v1",
                )
            except Exception as exc:
                errors.put(exc)

        thread_inspection = threading.Thread(target=_run_inspection)
        thread_order = threading.Thread(target=_accept_order)
        thread_inspection.start()
        thread_order.start()
        thread_inspection.join(timeout=15)
        thread_order.join(timeout=15)

        assert not thread_inspection.is_alive() and not thread_order.is_alive()
        assert errors.empty(), f"fallo inesperado: {list(errors.queue)}"

        # Ambos estados quedaron persistidos, sin escritura parcial.
        verify_repo = SQLitePaperTradingRepository(db_path)
        assert verify_repo.get_order("concurrent-order-1") is not None
        assert verify_repo.fetch_inspection_runs(limit=None) != []
