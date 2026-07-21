"""
Interfaz común que debe cumplir cualquier repositorio de Paper Trading (Etapa 6.3).

Sigue el mismo patrón que MarketDataRepository/IndicatorRepository
(src/database/base.py), SignalRepository (src/signals/base.py) y
AIRepository (src/ai/repository.py): el resto del proyecto (un futuro
PaperTradingService, todavía no construido) no necesita saber si estos
datos se guardan en SQLite, PostgreSQL o cualquier otro motor.

Esta interfaz representa únicamente persistencia -- guardar, leer,
filtrar, contar -- nunca lógica de negocio. Ningún método aquí simula un
fill, calcula PnL a partir de precios, valida riesgo ni decide
transiciones de estado: eso ya vive en los motores puros de la Etapa
6.2 (fill_engine.py, position_engine.py, pnl_engine.py, risk_engine.py),
que esta interfaz no conoce ni importa.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.paper_trading.alert_models import AlertStatus, InspectionAlert
from src.paper_trading.enums import OrderStatus
from src.paper_trading.inspection_models import ScheduledInspectionRun
from src.paper_trading.models import (
    CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade,
)
from src.paper_trading.reconciliation_models import ReconciliationAuditRecord


class PaperTradingRepository(ABC):
    @abstractmethod
    def init(self) -> None:
        """Prepara el almacenamiento (crear tablas/índices) si aún no existe. Idempotente."""

    # --- Order ----------------------------------------------------------

    @abstractmethod
    def save_order(self, order: Order) -> None:
        """Inserta la orden si es nueva, o actualiza su fila por `id` si ya existía."""

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """Devuelve la orden con ese id, o None si no existe."""

    @abstractmethod
    def fetch_orders(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[OrderStatus] = None,
        limit: Optional[int] = None,
    ) -> list[Order]:
        """Devuelve órdenes que cumplan los filtros dados, más recientes primero."""

    # --- Execution --------------------------------------------------------

    @abstractmethod
    def save_execution(self, execution: Execution) -> None:
        """Inserta una ejecución nueva (histórica e inmutable). Falla si el id ya existe."""

    @abstractmethod
    def fetch_executions_by_order(self, order_id: str) -> list[Execution]:
        """Devuelve las ejecuciones de una orden, en el orden en que ocurrieron."""

    @abstractmethod
    def fetch_executions(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Execution]:
        """Devuelve ejecuciones que cumplan los filtros dados, más recientes primero."""

    # --- Trade --------------------------------------------------------------

    @abstractmethod
    def save_trade(self, trade: Trade) -> None:
        """Inserta un trade cerrado (histórico e inmutable). Falla si el id ya existe."""

    @abstractmethod
    def fetch_trades(
        self,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Trade]:
        """Devuelve trades que cumplan los filtros dados, más recientes primero."""

    # --- Position -------------------------------------------------------

    @abstractmethod
    def save_position(self, position: Position) -> None:
        """Inserta o actualiza (upsert) la posición por (exchange, symbol)."""

    @abstractmethod
    def get_position(self, exchange: str, symbol: str) -> Optional[Position]:
        """Devuelve la posición actual de ese símbolo, o None si nunca se guardó."""

    @abstractmethod
    def fetch_positions(self, include_flat: bool = True) -> list[Position]:
        """Devuelve todas las posiciones guardadas, ordenadas por exchange y symbol."""

    # --- CashBalance ------------------------------------------------------

    @abstractmethod
    def save_cash_balance(self, cash_balance: CashBalance) -> None:
        """Inserta o actualiza (upsert) el saldo de esa moneda."""

    @abstractmethod
    def get_cash_balance(self, currency: str = "USDT") -> Optional[CashBalance]:
        """Devuelve el saldo actual de esa moneda, o None si nunca se guardó."""

    @abstractmethod
    def fetch_cash_balances(self) -> list[CashBalance]:
        """Devuelve todos los saldos guardados, uno por moneda (Etapa 6.8:
        ReconciliationEngine.analyze() necesita el conjunto completo, no
        solo el de una moneda)."""

    # --- Snapshots ------------------------------------------------------

    @abstractmethod
    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Inserta un snapshot de cartera nuevo (histórico e inmutable)."""

    @abstractmethod
    def fetch_portfolio_history(self, limit: Optional[int] = None) -> list[PortfolioSnapshot]:
        """Devuelve snapshots de cartera, más recientes primero."""

    @abstractmethod
    def save_pnl_snapshot(self, snapshot: PnLSnapshot) -> None:
        """Inserta un snapshot de PnL por símbolo nuevo (histórico e inmutable)."""

    @abstractmethod
    def fetch_pnl_history(
        self, exchange: str, symbol: str, limit: Optional[int] = None,
    ) -> list[PnLSnapshot]:
        """Devuelve snapshots de PnL de un símbolo, más recientes primero."""

    # --- Transacción atómica de fill --------------------------------------

    @abstractmethod
    def save_fill_transaction(
        self,
        order: Order,
        execution: Execution,
        position: Position,
        cash_balance: CashBalance,
        trade: Optional[Trade] = None,
        portfolio_snapshot: Optional[PortfolioSnapshot] = None,
        pnl_snapshot: Optional[PnLSnapshot] = None,
    ) -> None:
        """Persiste el resultado completo de un fill en una única transacción atómica.

        Todo o nada: si cualquier escritura falla (ej. un id duplicado),
        ninguna de las demás queda aplicada.
        """

    # --- Transacciones atómicas de aceptación/cancelación (Etapa 6.7) ------

    @abstractmethod
    def save_order_acceptance_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        """Persiste atómicamente una Order recién aceptada (PENDING, con
        reserva) junto con el CashBalance/Position que la reserva afectó.
        """

    @abstractmethod
    def save_order_cancellation_transaction(
        self, order: Order, cash_balance: CashBalance, position: Position,
    ) -> None:
        """Persiste atómicamente una Order cancelada (CANCELLED, reserva ya
        liberada) junto con el CashBalance/Position ya actualizados.
        """

    # --- PnL realizado: fuente de verdad y reconciliación ------------------

    @abstractmethod
    def calculate_realized_pnl(
        self, exchange: Optional[str] = None, symbol: Optional[str] = None,
    ) -> Decimal:
        """Suma exacta (Decimal) de Trade.net_pnl que cumple los filtros dados.

        Los Trade persistidos son la fuente primaria de verdad histórica
        del PnL realizado (ver docs/ARQUITECTURA_PAPER_TRADING.md).
        """

    @abstractmethod
    def check_position_pnl_consistency(self, exchange: str, symbol: str) -> bool:
        """True si Position.realized_pnl_to_date == calculate_realized_pnl(exchange, symbol).

        False si no coincide, o si no existe una Position para ese símbolo.
        No modifica nada: solo informa.
        """

    # --- Reconciliación (Etapa 6.8, ver ARQUITECTURA_PAPER_TRADING.md §22) --

    @abstractmethod
    def save_reconciliation_audit_record(self, audit_record: ReconciliationAuditRecord) -> None:
        """Inserta una fila inmutable en paper_trading_reconciliation_audit,
        sin tocar CashBalance/Position. Usado tanto para dry-run (nada más
        cambia) como para registrar una reparación real que falló antes de
        poder aplicarse (ver §22.6/§22.9)."""

    @abstractmethod
    def save_reconciliation_transaction(
        self,
        cash_balances: list[CashBalance],
        positions: list[Position],
        audit_record: ReconciliationAuditRecord,
    ) -> None:
        """Persiste atómicamente (todo o nada) los CashBalance/Position ya
        recalculados por una reparación real, junto con su fila de
        auditoría. Nunca toca Order/Execution/Trade/snapshots (§22.8)."""

    # --- Automatización de inspecciones (Etapa 6.9, ver ARQUITECTURA_PAPER_TRADING.md §23) --

    @abstractmethod
    def get_latest_successful_inspection_run(self) -> Optional[ScheduledInspectionRun]:
        """La corrida exitosa (success=True) más reciente, o None si nunca
        hubo una. Fuente del "reporte anterior" para comparar (§23.10)."""

    @abstractmethod
    def get_latest_inspection_run(self) -> Optional[ScheduledInspectionRun]:
        """La corrida más reciente sin importar su resultado, o None si
        nunca hubo ninguna. Se usa para detectar si la corrida anterior
        falló (y así decidir si emitir SYSTEM_RECOVERED, §23.11) --
        distinto de get_latest_successful_inspection_run()."""

    @abstractmethod
    def fetch_inspection_runs(self, limit: Optional[int] = None) -> list[ScheduledInspectionRun]:
        """Historial de corridas, más recientes primero."""

    @abstractmethod
    def fetch_pending_inspection_alerts(self, limit: Optional[int] = None) -> list[InspectionAlert]:
        """Alertas en estado PENDING, más antiguas primero (para entregarlas en orden)."""

    @abstractmethod
    def get_inspection_alert_by_deduplication_key(self, deduplication_key: str) -> Optional[InspectionAlert]:
        """La alerta con esa deduplication_key, o None si nunca se creó una."""

    @abstractmethod
    def save_inspection_run_transaction(
        self, run: ScheduledInspectionRun, alerts: list[InspectionAlert],
    ) -> None:
        """Persiste atómicamente (todo o nada) una corrida de inspección y
        todas sus alertas nuevas. Nunca toca Order/Execution/Trade/
        CashBalance/Position (§23.8)."""

    @abstractmethod
    def update_inspection_alert_delivery(
        self,
        alert_id: str,
        status: AlertStatus,
        delivery_attempts: int,
        last_error: Optional[str],
        delivered_at: Optional[datetime],
    ) -> None:
        """Actualiza el estado de entrega de una alerta ya persistida (§23.9)."""
