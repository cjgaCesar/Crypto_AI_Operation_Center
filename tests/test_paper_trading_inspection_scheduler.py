"""
Pruebas para src/paper_trading/inspection_scheduler.py (Etapa 6.9).

Nunca usa sleeps reales: `InspectionScheduler` recibe un `sleep_fn` falso
y `max_cycles` acotado. `main()` se prueba con `load_settings`
monkeypatcheado, nunca contra config/config.yaml ni data/crypto_data.db.
"""

from decimal import Decimal

import pytest

from src.paper_trading import inspection_scheduler
from src.paper_trading.inspection_scheduler import InspectionScheduler
from src.utils.config import PaperTradingConfig, ReconciliationInspectionConfig


class FakeJob:
    def __init__(self, fail_after: int = None):
        self.calls = 0
        self._fail_after = fail_after

    def run_once(self):
        self.calls += 1
        if self._fail_after is not None and self.calls > self._fail_after:
            raise RuntimeError("boom")
        return None


class RecordingSleep:
    def __init__(self):
        self.calls: list = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class TestConstructorValidation:
    def test_interval_must_be_at_least_one_minute(self):
        with pytest.raises(ValueError):
            InspectionScheduler(job=FakeJob(), interval_minutes=0)


class TestRunOnStartup:
    def test_run_on_startup_false_does_not_run_before_first_sleep(self):
        job = FakeJob()
        sleep = RecordingSleep()
        scheduler = InspectionScheduler(job=job, interval_minutes=1, sleep_fn=sleep)
        scheduler.run_forever(run_on_startup=False, max_cycles=0)
        assert job.calls == 0

    def test_run_on_startup_true_runs_immediately(self):
        job = FakeJob()
        sleep = RecordingSleep()
        scheduler = InspectionScheduler(job=job, interval_minutes=1, sleep_fn=sleep)
        scheduler.run_forever(run_on_startup=True, max_cycles=0)
        assert job.calls == 1
        assert sleep.calls == []  # sin ciclos periódicos todavía


class TestInterval:
    def test_sleep_called_with_interval_in_seconds(self):
        job = FakeJob()
        sleep = RecordingSleep()
        scheduler = InspectionScheduler(job=job, interval_minutes=2, sleep_fn=sleep)
        scheduler.run_forever(run_on_startup=False, max_cycles=3)
        assert sleep.calls == [120, 120, 120]
        assert job.calls == 3


class TestSuccessfulAndFailedCycles:
    def test_successful_cycle_runs_job(self):
        job = FakeJob()
        scheduler = InspectionScheduler(job=job, interval_minutes=1, sleep_fn=RecordingSleep())
        scheduler.run_forever(run_on_startup=False, max_cycles=1)
        assert job.calls == 1

    def test_failed_cycle_does_not_stop_scheduler(self):
        job = FakeJob(fail_after=0)  # falla en toda llamada
        scheduler = InspectionScheduler(job=job, interval_minutes=1, sleep_fn=RecordingSleep())
        scheduler.run_forever(run_on_startup=False, max_cycles=3)
        assert job.calls == 3  # las 3 corridas se intentaron pese al fallo


class TestNoOverlapDelegatedToJob:
    """El scheduler no implementa su propio lock: delega en InspectionJob
    (que sí lo tiene, ver test_paper_trading_inspection_job.py). Aquí solo
    confirmamos que el scheduler llama run_once() una vez por ciclo."""

    def test_run_once_called_exactly_once_per_cycle(self):
        job = FakeJob()
        scheduler = InspectionScheduler(job=job, interval_minutes=1, sleep_fn=RecordingSleep())
        scheduler.run_forever(run_on_startup=True, max_cycles=2)
        assert job.calls == 3  # 1 startup + 2 ciclos


class TestMainDisabled:
    def test_main_returns_zero_and_does_not_build_context_when_disabled(self, monkeypatch):
        class FakeSettings:
            paper_trading = PaperTradingConfig(
                enabled=True, database_path="unused", initial_capital=Decimal("10000"), currency="USDT",
                fee_rate=Decimal("0.001"), max_order_value=Decimal("1000"), max_position_value=Decimal("5000"),
                rules_version="v1", reconciliation_inspection=ReconciliationInspectionConfig(enabled=False),
            )

        monkeypatch.setattr(inspection_scheduler, "load_settings", lambda: FakeSettings())

        def _boom_if_called(*a, **k):
            raise AssertionError("build_paper_trading_context no debería llamarse con enabled=False")

        monkeypatch.setattr(inspection_scheduler, "build_paper_trading_context", _boom_if_called)

        exit_code = inspection_scheduler.main()
        assert exit_code == 0


class TestMainKeyboardInterrupt:
    def test_main_handles_keyboard_interrupt_cleanly(self, tmp_path, monkeypatch):
        class FakeSettings:
            paper_trading = PaperTradingConfig(
                enabled=True, database_path=str(tmp_path / "test.db"), initial_capital=Decimal("10000"),
                currency="USDT", fee_rate=Decimal("0.001"), max_order_value=Decimal("1000"),
                max_position_value=Decimal("5000"), rules_version="v1",
                reconciliation_inspection=ReconciliationInspectionConfig(enabled=True, run_on_startup=False),
            )

        monkeypatch.setattr(inspection_scheduler, "load_settings", lambda: FakeSettings())

        class InterruptingScheduler:
            def run_forever(self, run_on_startup, max_cycles=None):
                raise KeyboardInterrupt()

        monkeypatch.setattr(inspection_scheduler, "_build_scheduler", lambda settings: InterruptingScheduler())

        exit_code = inspection_scheduler.main()
        assert exit_code == 0


class TestIsolation:
    @staticmethod
    def _import_lines():
        source = open(inspection_scheduler.__file__, encoding="utf-8").read()
        return [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]

    def test_does_not_import_binance(self):
        assert not any("binance" in line.lower() for line in self._import_lines())

    def test_does_not_import_signals(self):
        assert not any("signals" in line.lower() for line in self._import_lines())

    def test_does_not_import_ai(self):
        assert not any(line.strip().startswith(("import src.ai", "from src.ai")) for line in self._import_lines())

    def test_does_not_import_dashboard(self):
        assert not any("dashboard" in line.lower() for line in self._import_lines())

    def test_does_not_import_main_module(self):
        assert not any("src.main" in line or "src import main" in line for line in self._import_lines())

    def test_does_not_use_schedule_library(self):
        source = open(inspection_scheduler.__file__, encoding="utf-8").read()
        assert "import schedule" not in source

    def test_never_calls_repair(self):
        source = open(inspection_scheduler.__file__, encoding="utf-8").read()
        assert ".repair(" not in source
        assert "repair_reconciliation" not in source

    def test_never_calls_run_full_cycle(self):
        source = open(inspection_scheduler.__file__, encoding="utf-8").read()
        assert "run_full_cycle(" not in source
