"""
Scheduler independiente de inspecciones de reconciliación (Etapa 6.9).

Proceso completamente separado de src/main.py: no importa
`run_full_cycle`, `BinanceExchangeClient`, `SignalEngine`/`SignalService`,
ni ningún módulo de `src.ai`/`src.dashboard`. No usa la librería
`schedule` (ya usada por main.py, ver §23.15): implementa su propio loop
simple, con `sleep_fn` inyectable para poder probarlo sin esperas reales
(Paso 41).

Uso:
    python -m src.paper_trading.inspection_scheduler
"""

import logging
import sys
import time
from decimal import Decimal
from typing import Callable, Optional

from src.paper_trading.composition import build_paper_trading_context
from src.paper_trading.inspection_job import InspectionJob
from src.paper_trading.runtime import SystemClock, UUIDIdGenerator
from src.utils.config import Settings, load_settings

logger = logging.getLogger(__name__)


class _UnavailableMarketPriceProvider:
    """El scheduler de inspección nunca consulta precios (§23.2)."""

    def get_current_price(self, exchange: str, symbol: str) -> Decimal:
        raise NotImplementedError("El scheduler de inspección nunca debería consultar un precio de mercado.")

    def get_current_prices(self, symbols: list[tuple[str, str]]) -> dict[tuple[str, str], Decimal]:
        raise NotImplementedError("El scheduler de inspección nunca debería consultar un precio de mercado.")


class InspectionScheduler:
    """Loop propio y simple (§23.15): ejecuta `job.run_once()` cada
    `interval_minutes`, con `sleep_fn` inyectable para pruebas
    deterministas (nunca espera real en los tests)."""

    def __init__(
        self,
        job: InspectionJob,
        interval_minutes: float,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if interval_minutes < 1:
            raise ValueError("interval_minutes debe ser >= 1.")
        self._job = job
        self._interval_seconds = interval_minutes * 60
        self._sleep_fn = sleep_fn

    def run_cycle(self) -> None:
        """Ejecuta un único ciclo, capturando cualquier excepción no
        controlada (Paso 4, principio 13: un fallo no debe detener el
        scheduler)."""
        try:
            self._job.run_once()
        except Exception:
            logger.exception("Fallo no controlado en un ciclo del scheduler de inspección; se continúa.")

    def run_forever(self, run_on_startup: bool, max_cycles: Optional[int] = None) -> None:
        """`max_cycles=None` corre indefinidamente (uso real); un entero
        acota el número de iteraciones (uso en pruebas)."""
        if run_on_startup:
            self.run_cycle()

        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            self._sleep_fn(self._interval_seconds)
            self.run_cycle()
            cycles += 1


def _build_scheduler(settings: Settings) -> InspectionScheduler:
    context = build_paper_trading_context(
        config=settings.paper_trading,
        clock=SystemClock(),
        id_generator=UUIDIdGenerator(),
        market_price_provider=_UnavailableMarketPriceProvider(),
    )
    return InspectionScheduler(
        job=context.inspection_job,
        interval_minutes=settings.paper_trading.reconciliation_inspection.interval_minutes,
    )


def main() -> int:
    settings = load_settings()
    inspection_config = settings.paper_trading.reconciliation_inspection

    if not inspection_config.enabled:
        logger.info(
            "Scheduler de inspección de reconciliación deshabilitado "
            "(paper_trading.reconciliation_inspection.enabled=false)."
        )
        return 0

    scheduler = _build_scheduler(settings)
    logger.info(
        "Scheduler de inspección de reconciliación en ejecución (cada %s minutos). Presiona Ctrl+C para detenerlo.",
        inspection_config.interval_minutes,
    )
    try:
        scheduler.run_forever(run_on_startup=inspection_config.run_on_startup)
    except KeyboardInterrupt:
        logger.info("Scheduler de inspección de reconciliación detenido manualmente por el usuario.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
