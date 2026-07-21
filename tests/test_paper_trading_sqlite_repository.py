"""
Pruebas para src/paper_trading/sqlite_repository.py (SQLitePaperTradingRepository)
y, de forma indirecta, para la interfaz src/paper_trading/base.py
(PaperTradingRepository): esta clase es la única implementación real
hoy, así que probarla cubre el contrato completo.

Usa `tmp_path` para una base SQLite real y temporal en todos los casos
(no se mockea sqlite3): así se verifican tablas, índices, foreign keys
y round-trip de Decimal contra un archivo real, sin tocar nunca
data/crypto_data.db.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.paper_trading.alert_models import AlertStatus, AlertType, InspectionAlert, build_deduplication_key
from src.paper_trading.enums import OrderSide, OrderSource, OrderStatus, OrderType, PositionSide, TradeSide
from src.paper_trading.inspection_models import IssueIdentity, ScheduledInspectionRun, build_issue_identity
from src.paper_trading.models import CashBalance, Execution, Order, PnLSnapshot, PortfolioSnapshot, Position, Trade
from src.paper_trading.reconciliation_models import (
    IssueCode, IssueSeverity, ReconciliationAuditRecord, ReconciliationIssue, ReconciliationReport,
)
from src.paper_trading.sqlite_repository import SQLitePaperTradingRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _repo(tmp_path) -> SQLitePaperTradingRepository:
    repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
    repo.init()
    return repo


def _order(**overrides) -> Order:
    defaults = dict(
        id="order-1", exchange="Binance", symbol="BTCUSDT",
        side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Decimal("0.1"), status=OrderStatus.PENDING,
        source=OrderSource.MANUAL, created_at=_now(), updated_at=_now(),
    )
    defaults.update(overrides)
    return Order(**defaults)


def _execution(**overrides) -> Execution:
    defaults = dict(
        id="exec-1", order_id="order-1", exchange="Binance", symbol="BTCUSDT",
        quantity=Decimal("0.1"), price=Decimal("50000"), fee=Decimal("5"),
        executed_at=_now(),
    )
    defaults.update(overrides)
    return Execution(**defaults)


def _trade(**overrides) -> Trade:
    opened = _now()
    if "net_pnl" in overrides and "gross_pnl" not in overrides and "fees" not in overrides:
        overrides.setdefault("gross_pnl", overrides["net_pnl"])
        overrides.setdefault("fees", Decimal("0"))
    defaults = dict(
        id="trade-1", exchange="Binance", symbol="BTCUSDT", side=TradeSide.LONG,
        quantity=Decimal("0.1"), entry_price=Decimal("50000"), exit_price=Decimal("54000"),
        gross_pnl=Decimal("400"), fees=Decimal("5.4"), net_pnl=Decimal("394.6"),
        opened_at=opened, closed_at=opened + timedelta(minutes=5),
        exit_execution_id="exec-1",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def _position(**overrides) -> Position:
    defaults = dict(
        exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG,
        quantity=Decimal("0.1"), average_entry_price=Decimal("50000"), updated_at=_now(),
    )
    defaults.update(overrides)
    return Position(**defaults)


def _flat_position(**overrides) -> Position:
    defaults = dict(exchange="Binance", symbol="BTCUSDT", side=PositionSide.FLAT, quantity=Decimal("0"), updated_at=_now())
    defaults.update(overrides)
    return Position(**defaults)


def _cash_balance(**overrides) -> CashBalance:
    defaults = dict(total_balance=Decimal("10000"), updated_at=_now())
    defaults.update(overrides)
    return CashBalance(**defaults)


def _portfolio_snapshot(**overrides) -> PortfolioSnapshot:
    defaults = dict(
        timestamp=_now(), cash_balance=Decimal("5000"), positions_value=Decimal("5000"),
        total_equity=Decimal("10000"), unrealized_pnl_total=Decimal("0"), realized_pnl_cumulative=Decimal("0"),
    )
    defaults.update(overrides)
    return PortfolioSnapshot(**defaults)


def _pnl_snapshot(**overrides) -> PnLSnapshot:
    defaults = dict(
        timestamp=_now(), exchange="Binance", symbol="BTCUSDT",
        position_quantity=Decimal("0.1"), unrealized_pnl=Decimal("50"), realized_pnl_cumulative=Decimal("0"),
    )
    defaults.update(overrides)
    return PnLSnapshot(**defaults)


def _audit_record(**overrides) -> ReconciliationAuditRecord:
    now = _now()
    defaults = dict(
        id="audit-1", started_at=now, completed_at=now, dry_run=True, success=True,
        issue_count=1, repaired_count=0, report_json="{}", operations_json="[]",
    )
    defaults.update(overrides)
    return ReconciliationAuditRecord(**defaults)


def _reconciliation_issue(**overrides) -> ReconciliationIssue:
    defaults = dict(
        code=IssueCode.ORPHAN_CASH_RESERVATION, severity=IssueSeverity.ERROR, entity_type="CashBalance",
        entity_id="USDT", exchange=None, symbol=None, description="x", expected_value=Decimal("0"),
        actual_value=Decimal("100"), repairable=True, suggested_action="y", detected_at=_now(),
    )
    defaults.update(overrides)
    return ReconciliationIssue(**defaults)


def _inspection_run(**overrides) -> ScheduledInspectionRun:
    now = _now()
    report = ReconciliationReport(generated_at=now, issues=(_reconciliation_issue(),))
    defaults = dict(
        id="run-1", started_at=now, completed_at=now, success=True, report=report, previous_run_id=None,
        new_issue_count=1, resolved_issue_count=0, persistent_issue_count=0, changed_issue_count=0, alert_count=1,
    )
    defaults.update(overrides)
    return ScheduledInspectionRun(**defaults)


def _inspection_alert(**overrides) -> InspectionAlert:
    identity = IssueIdentity(
        code="ORPHAN_CASH_RESERVATION", entity_type="CashBalance", entity_id="USDT", exchange=None, symbol=None,
    )
    defaults = dict(
        id="alert-1", run_id="run-1", alert_type=AlertType.NEW_ISSUE, issue_identity=identity,
        issue_code="ORPHAN_CASH_RESERVATION", severity=IssueSeverity.ERROR, title="t", message="m",
        deduplication_key=build_deduplication_key(AlertType.NEW_ISSUE, issue_identity=identity, severity=IssueSeverity.ERROR),
        status=AlertStatus.PENDING, delivery_attempts=0, last_error=None, created_at=_now(),
    )
    defaults.update(overrides)
    return InspectionAlert(**defaults)


# --- INIT --------------------------------------------------------------------

class TestInit:
    def test_creates_all_tables(self, tmp_path):
        repo = _repo(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        expected = {
            "paper_trading_orders", "paper_trading_executions", "paper_trading_trades",
            "paper_trading_positions", "paper_trading_cash_balances",
            "paper_trading_portfolio_snapshots", "paper_trading_pnl_snapshots",
        }
        assert expected.issubset(tables)

    def test_creates_indexes(self, tmp_path):
        repo = _repo(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        finally:
            conn.close()
        assert "idx_paper_trading_orders_lookup" in indexes
        assert "idx_paper_trading_executions_order" in indexes
        assert "idx_paper_trading_executions_lookup" in indexes
        assert "idx_paper_trading_trades_lookup" in indexes
        assert "idx_paper_trading_portfolio_snapshots_timestamp" in indexes
        assert "idx_paper_trading_pnl_snapshots_lookup" in indexes

    def test_is_idempotent_and_preserves_data(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())

        repo.init()
        repo.init()

        assert repo.get_order("order-1") is not None

    def test_migrates_legacy_schema_without_reservation_columns(self, tmp_path):
        """Base creada antes de la Etapa 6.7 (sin las 4 columnas de
        reserva en paper_trading_orders): init() debe agregarlas sin
        perder ni alterar ningún registro existente."""
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE paper_trading_orders (
                id TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity TEXT NOT NULL,
                limit_price TEXT,
                status TEXT NOT NULL,
                filled_quantity TEXT NOT NULL,
                average_fill_price TEXT,
                source TEXT NOT NULL,
                linked_recommendation_id TEXT,
                rejection_reason TEXT,
                cancellation_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO paper_trading_orders "
            "(id, exchange, symbol, side, order_type, quantity, status, filled_quantity, source, created_at, updated_at) "
            "VALUES ('legacy-1', 'Binance', 'BTCUSDT', 'BUY', 'MARKET', '0.1', 'NEW', '0', 'MANUAL', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        columns_before = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(paper_trading_orders)")}
        assert "reserved_price" not in columns_before

        repo = SQLitePaperTradingRepository(db_path)
        repo.init()

        columns_after = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(paper_trading_orders)")}
        assert {"reserved_price", "reserved_notional", "reserved_fee", "reserved_quantity"}.issubset(columns_after)

        legacy_order = repo.get_order("legacy-1")
        assert legacy_order is not None
        assert legacy_order.quantity == Decimal("0.1")
        assert legacy_order.reserved_price is None

    def test_connections_have_foreign_keys_enabled(self, tmp_path):
        repo = _repo(tmp_path)
        conn = repo._get_connection()
        try:
            (value,) = conn.execute("PRAGMA foreign_keys").fetchone()
        finally:
            conn.close()
        assert value == 1

    def test_does_not_touch_the_real_project_database(self, tmp_path):
        import os
        real_db_path = os.path.abspath("data/crypto_data.db")
        before = os.path.getmtime(real_db_path) if os.path.exists(real_db_path) else None

        repo = _repo(tmp_path)
        repo.save_order(_order())

        assert os.path.abspath(repo.db_path) != real_db_path
        after = os.path.getmtime(real_db_path) if os.path.exists(real_db_path) else None
        assert before == after


# --- ORDER --------------------------------------------------------------

class TestOrder:
    def test_save_and_get_roundtrip(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        repo.save_order(order)
        assert repo.get_order("order-1") == order

    def test_get_returns_none_when_missing(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_order("does-not-exist") is None

    def test_upsert_on_status_change_preserves_created_at(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        repo.save_order(order)
        updated = Order(**{
            **order.model_dump(), "status": OrderStatus.FILLED,
            "filled_quantity": Decimal("0.1"), "average_fill_price": Decimal("50000"),
            "updated_at": order.updated_at + timedelta(seconds=1),
        })
        repo.save_order(updated)
        fetched = repo.get_order("order-1")
        assert fetched.status == OrderStatus.FILLED
        assert fetched.created_at == order.created_at

    def test_decimal_roundtrip_exact(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order(quantity=Decimal("123456789.123456789"))
        repo.save_order(order)
        assert repo.get_order("order-1").quantity == Decimal("123456789.123456789")

    def test_optional_fields_roundtrip_as_none(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        repo.save_order(order)
        fetched = repo.get_order("order-1")
        assert fetched.limit_price is None
        assert fetched.average_fill_price is None
        assert fetched.expires_at is None

    def test_optional_fields_roundtrip_with_values(self, tmp_path):
        repo = _repo(tmp_path)
        expires = _now() + timedelta(hours=1)
        order = _order(
            order_type=OrderType.LIMIT, limit_price=Decimal("49000"), expires_at=expires,
        )
        repo.save_order(order)
        fetched = repo.get_order("order-1")
        assert fetched.limit_price == Decimal("49000")
        assert fetched.expires_at == expires

    def test_filter_by_exchange(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(id="o1", exchange="Binance"))
        repo.save_order(_order(id="o2", exchange="Kraken"))
        results = repo.fetch_orders(exchange="Kraken")
        assert [o.id for o in results] == ["o2"]

    def test_filter_by_symbol(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(id="o1", symbol="BTCUSDT"))
        repo.save_order(_order(id="o2", symbol="ETHUSDT"))
        results = repo.fetch_orders(symbol="ETHUSDT")
        assert [o.id for o in results] == ["o2"]

    def test_filter_by_status(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(id="o1", status=OrderStatus.NEW))
        repo.save_order(_order(id="o2", status=OrderStatus.PENDING))
        results = repo.fetch_orders(status=OrderStatus.PENDING)
        assert [o.id for o in results] == ["o2"]

    def test_limit(self, tmp_path):
        repo = _repo(tmp_path)
        base = _now()
        for i in range(3):
            repo.save_order(_order(id=f"o{i}", created_at=base + timedelta(seconds=i), updated_at=base))
        results = repo.fetch_orders(limit=2)
        assert len(results) == 2

    def test_ordered_by_created_at_desc(self, tmp_path):
        repo = _repo(tmp_path)
        base = _now()
        repo.save_order(_order(id="oldest", created_at=base, updated_at=base))
        repo.save_order(_order(id="newest", created_at=base + timedelta(minutes=1), updated_at=base))
        results = repo.fetch_orders()
        assert [o.id for o in results] == ["newest", "oldest"]


# --- EXECUTION ------------------------------------------------------------

class TestExecution:
    def test_save_and_fetch_by_order(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        execution = _execution()
        repo.save_execution(execution)
        results = repo.fetch_executions_by_order("order-1")
        assert results == [execution]

    def test_fetch_by_order_ordered_ascending(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(quantity=Decimal("1")))
        base = _now()
        repo.save_execution(_execution(id="e1", executed_at=base + timedelta(minutes=2)))
        repo.save_execution(_execution(id="e2", executed_at=base))
        results = repo.fetch_executions_by_order("order-1")
        assert [e.id for e in results] == ["e2", "e1"]

    def test_fetch_general_ordered_descending(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(quantity=Decimal("1")))
        base = _now()
        repo.save_execution(_execution(id="e1", executed_at=base))
        repo.save_execution(_execution(id="e2", executed_at=base + timedelta(minutes=2)))
        results = repo.fetch_executions()
        assert [e.id for e in results] == ["e2", "e1"]

    def test_duplicate_id_fails(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_execution(_execution())

    def test_foreign_key_to_order_is_enforced(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_execution(_execution(order_id="does-not-exist"))

    def test_decimal_roundtrip_exact(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(quantity=Decimal("0.00000001")))
        repo.save_execution(_execution(quantity=Decimal("0.00000001"), price=Decimal("123456789.123456789")))
        fetched = repo.fetch_executions_by_order("order-1")[0]
        assert fetched.quantity == Decimal("0.00000001")
        assert fetched.price == Decimal("123456789.123456789")

    def test_filter_by_exchange_and_symbol(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order(id="o1", exchange="Binance", symbol="BTCUSDT"))
        repo.save_order(_order(id="o2", exchange="Binance", symbol="ETHUSDT"))
        repo.save_execution(_execution(id="e1", order_id="o1", exchange="Binance", symbol="BTCUSDT"))
        repo.save_execution(_execution(id="e2", order_id="o2", exchange="Binance", symbol="ETHUSDT"))
        results = repo.fetch_executions(symbol="ETHUSDT")
        assert [e.id for e in results] == ["e2"]


# --- TRADE --------------------------------------------------------------

class TestTrade:
    def test_save_and_fetch(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        trade = _trade()
        repo.save_trade(trade)
        results = repo.fetch_trades()
        assert results == [trade]

    def test_ordered_by_closed_at_desc(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        base = _now()
        repo.save_trade(_trade(id="t1", closed_at=base))
        repo.save_trade(_trade(id="t2", closed_at=base + timedelta(minutes=5)))
        results = repo.fetch_trades()
        assert [t.id for t in results] == ["t2", "t1"]

    def test_duplicate_id_fails(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade())
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_trade(_trade())

    def test_foreign_key_to_execution_is_enforced(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_trade(_trade(exit_execution_id="does-not-exist"))

    def test_negative_net_pnl(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        trade = _trade(gross_pnl=Decimal("-100"), fees=Decimal("2"), net_pnl=Decimal("-102"))
        repo.save_trade(trade)
        assert repo.fetch_trades()[0].net_pnl == Decimal("-102")

    def test_decimal_precision(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        trade = _trade(net_pnl=Decimal("0.1"), gross_pnl=Decimal("0.1"), fees=Decimal("0"))
        repo.save_trade(trade)
        assert repo.fetch_trades()[0].net_pnl == Decimal("0.1")


# --- POSITION -------------------------------------------------------

class TestPosition:
    def test_save_and_get(self, tmp_path):
        repo = _repo(tmp_path)
        position = _position()
        repo.save_position(position)
        assert repo.get_position("Binance", "BTCUSDT") == position

    def test_get_returns_none_when_missing(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_position("Binance", "DOESNOTEXIST") is None

    def test_upsert_by_exchange_symbol(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_position(_position(quantity=Decimal("0.1")))
        repo.save_position(_position(quantity=Decimal("0.2")))
        assert repo.get_position("Binance", "BTCUSDT").quantity == Decimal("0.2")

    def test_long_and_flat_roundtrip(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_position(_position(exchange="Binance", symbol="BTCUSDT", side=PositionSide.LONG))
        repo.save_position(_flat_position(exchange="Binance", symbol="ETHUSDT"))
        assert repo.get_position("Binance", "BTCUSDT").side == PositionSide.LONG
        assert repo.get_position("Binance", "ETHUSDT").side == PositionSide.FLAT

    def test_fetch_positions_include_flat_true(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_position(_position(exchange="Binance", symbol="BTCUSDT"))
        repo.save_position(_flat_position(exchange="Binance", symbol="ETHUSDT"))
        results = repo.fetch_positions(include_flat=True)
        assert len(results) == 2

    def test_fetch_positions_include_flat_false(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_position(_position(exchange="Binance", symbol="BTCUSDT"))
        repo.save_position(_flat_position(exchange="Binance", symbol="ETHUSDT"))
        results = repo.fetch_positions(include_flat=False)
        assert len(results) == 1
        assert results[0].symbol == "BTCUSDT"

    def test_realized_pnl_to_date_roundtrip(self, tmp_path):
        repo = _repo(tmp_path)
        position = _position(realized_pnl_to_date=Decimal("394.6"))
        repo.save_position(position)
        assert repo.get_position("Binance", "BTCUSDT").realized_pnl_to_date == Decimal("394.6")

    def test_reserved_quantity_roundtrip(self, tmp_path):
        repo = _repo(tmp_path)
        position = _position(reserved_quantity=Decimal("0.05"))
        repo.save_position(position)
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0.05")

    def test_deterministic_order(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_position(_position(exchange="Binance", symbol="ETHUSDT"))
        repo.save_position(_position(exchange="Binance", symbol="BTCUSDT"))
        repo.save_position(_position(exchange="Kraken", symbol="BTCUSDT"))
        results = repo.fetch_positions()
        assert [(p.exchange, p.symbol) for p in results] == [
            ("Binance", "BTCUSDT"), ("Binance", "ETHUSDT"), ("Kraken", "BTCUSDT"),
        ]


# --- CASH BALANCE ---------------------------------------------------------

class TestCashBalance:
    def test_save_and_get(self, tmp_path):
        repo = _repo(tmp_path)
        cash = _cash_balance()
        repo.save_cash_balance(cash)
        assert repo.get_cash_balance("USDT") == cash

    def test_get_returns_none_when_missing(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_cash_balance("USDT") is None

    def test_upsert_by_currency(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(total_balance=Decimal("10000")))
        repo.save_cash_balance(_cash_balance(total_balance=Decimal("9995")))
        assert repo.get_cash_balance("USDT").total_balance == Decimal("9995")

    def test_reserved_balance_roundtrip(self, tmp_path):
        repo = _repo(tmp_path)
        cash = _cash_balance(reserved_balance=Decimal("100"))
        repo.save_cash_balance(cash)
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("100")

    def test_decimal_exact(self, tmp_path):
        repo = _repo(tmp_path)
        cash = _cash_balance(total_balance=Decimal("0.1"))
        repo.save_cash_balance(cash)
        assert repo.get_cash_balance("USDT").total_balance == Decimal("0.1")


# --- SNAPSHOTS ------------------------------------------------------------

class TestSnapshots:
    def test_save_and_fetch_portfolio(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_portfolio_snapshot(_portfolio_snapshot())
        results = repo.fetch_portfolio_history()
        assert len(results) == 1
        assert results[0].id is not None

    def test_save_and_fetch_pnl(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_pnl_snapshot(_pnl_snapshot())
        results = repo.fetch_pnl_history("Binance", "BTCUSDT")
        assert len(results) == 1
        assert results[0].id is not None

    def test_portfolio_limit(self, tmp_path):
        repo = _repo(tmp_path)
        base = _now()
        for i in range(3):
            repo.save_portfolio_snapshot(_portfolio_snapshot(timestamp=base + timedelta(minutes=i)))
        assert len(repo.fetch_portfolio_history(limit=2)) == 2

    def test_portfolio_ordered_by_timestamp_desc(self, tmp_path):
        repo = _repo(tmp_path)
        base = _now()
        repo.save_portfolio_snapshot(_portfolio_snapshot(timestamp=base))
        repo.save_portfolio_snapshot(_portfolio_snapshot(timestamp=base + timedelta(minutes=5)))
        results = repo.fetch_portfolio_history()
        assert results[0].timestamp > results[1].timestamp

    def test_pnl_snapshot_negative(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_pnl_snapshot(_pnl_snapshot(unrealized_pnl=Decimal("-25")))
        assert repo.fetch_pnl_history("Binance", "BTCUSDT")[0].unrealized_pnl == Decimal("-25")

    def test_pnl_decimal_exact(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_pnl_snapshot(_pnl_snapshot(unrealized_pnl=Decimal("123456789.123456789")))
        assert repo.fetch_pnl_history("Binance", "BTCUSDT")[0].unrealized_pnl == Decimal("123456789.123456789")

    def test_pnl_ordered_by_timestamp_desc(self, tmp_path):
        repo = _repo(tmp_path)
        base = _now()
        repo.save_pnl_snapshot(_pnl_snapshot(timestamp=base))
        repo.save_pnl_snapshot(_pnl_snapshot(timestamp=base + timedelta(minutes=5)))
        results = repo.fetch_pnl_history("Binance", "BTCUSDT")
        assert results[0].timestamp > results[1].timestamp


# --- TRANSACCIÓN ----------------------------------------------------------

class TestSaveFillTransaction:
    def test_persists_full_fill(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order(status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"), average_fill_price=Decimal("50000"))
        execution = _execution()
        position = _position()
        cash = _cash_balance(total_balance=Decimal("9995"))
        repo.save_fill_transaction(order, execution, position, cash)
        assert repo.get_order("order-1").status == OrderStatus.FILLED
        assert repo.get_position("Binance", "BTCUSDT") == position
        assert repo.get_cash_balance("USDT") == cash
        assert repo.fetch_executions_by_order("order-1") == [execution]

    def test_persists_fill_with_trade(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order(side=OrderSide.SELL, status=OrderStatus.FILLED, filled_quantity=Decimal("0.1"), average_fill_price=Decimal("54000"))
        execution = _execution(price=Decimal("54000"), fee=Decimal("5.4"))
        position = _flat_position(realized_pnl_to_date=Decimal("394.6"))
        cash = _cash_balance(total_balance=Decimal("10394.6"))
        trade = _trade()
        repo.save_fill_transaction(order, execution, position, cash, trade=trade)
        assert repo.fetch_trades() == [trade]
        assert repo.calculate_realized_pnl() == Decimal("394.6")

    def test_persists_optional_snapshots(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        execution = _execution()
        position = _position()
        cash = _cash_balance()
        portfolio_snapshot = _portfolio_snapshot()
        pnl_snapshot = _pnl_snapshot()
        repo.save_fill_transaction(
            order, execution, position, cash,
            portfolio_snapshot=portfolio_snapshot, pnl_snapshot=pnl_snapshot,
        )
        assert len(repo.fetch_portfolio_history()) == 1
        assert len(repo.fetch_pnl_history("Binance", "BTCUSDT")) == 1

    def test_rejects_execution_order_id_mismatch(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        execution = _execution(order_id="other-order")
        with pytest.raises(ValueError):
            repo.save_fill_transaction(order, execution, _position(), _cash_balance())
        assert repo.get_order("order-1") is None

    def test_rejects_position_symbol_mismatch(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        execution = _execution()
        position = _position(symbol="ETHUSDT")
        with pytest.raises(ValueError):
            repo.save_fill_transaction(order, execution, position, _cash_balance())
        assert repo.get_order("order-1") is None

    def test_rejects_trade_exit_execution_id_mismatch(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        execution = _execution()
        trade = _trade(exit_execution_id="other-execution")
        with pytest.raises(ValueError):
            repo.save_fill_transaction(order, execution, _position(), _cash_balance(), trade=trade)
        assert repo.get_order("order-1") is None

    def test_rollback_on_duplicate_execution_leaves_no_partial_state(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        execution = _execution()
        position = _position()
        cash = _cash_balance(total_balance=Decimal("9995"))
        repo.save_fill_transaction(order, execution, position, cash)

        bad_order = Order(**{**order.model_dump(), "status": OrderStatus.CANCELLED, "cancellation_reason": "leaked"})
        bad_position = Position(**{**position.model_dump(), "quantity": Decimal("999")})
        bad_cash = CashBalance(**{**cash.model_dump(), "total_balance": Decimal("1")})

        with pytest.raises(sqlite3.IntegrityError):
            repo.save_fill_transaction(bad_order, execution, bad_position, bad_cash)

        assert repo.get_order("order-1").status == OrderStatus.PENDING
        assert repo.get_order("order-1").cancellation_reason is None
        assert repo.get_position("Binance", "BTCUSDT").quantity == Decimal("0.1")
        assert repo.get_cash_balance("USDT").total_balance == Decimal("9995")

    def test_rollback_on_duplicate_trade_leaves_no_partial_state(self, tmp_path):
        repo = _repo(tmp_path)
        order = _order()
        execution = _execution()
        position = _position()
        cash = _cash_balance(total_balance=Decimal("9995"))
        trade = _trade()
        repo.save_fill_transaction(order, execution, position, cash, trade=trade)

        new_execution = _execution(id="exec-2")
        new_order = Order(**{**order.model_dump(), "status": OrderStatus.CANCELLED})
        new_position = Position(**{**position.model_dump(), "quantity": Decimal("999")})
        new_cash = CashBalance(**{**cash.model_dump(), "total_balance": Decimal("1")})
        duplicate_trade = Trade(**{**trade.model_dump(), "exit_execution_id": "exec-2"})

        with pytest.raises(sqlite3.IntegrityError):
            repo.save_fill_transaction(new_order, new_execution, new_position, new_cash, trade=duplicate_trade)

        assert repo.get_order("order-1").status == OrderStatus.PENDING
        assert repo.get_position("Binance", "BTCUSDT").quantity == Decimal("0.1")
        assert repo.get_cash_balance("USDT").total_balance == Decimal("9995")
        assert repo.fetch_executions_by_order("order-1") == [execution]
        assert repo.fetch_trades() == [trade]


# --- TRANSACCIONES DE RESERVA (Etapa 6.7) ---------------------------------

class TestSaveOrderAcceptanceTransaction:
    def test_persists_buy_acceptance_atomically(self, tmp_path):
        repo = _repo(tmp_path)
        cash = _cash_balance(total_balance=Decimal("10000"))
        repo.save_cash_balance(cash)
        order = _order(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        reserved_cash = CashBalance(**{**cash.model_dump(), "reserved_balance": Decimal("5005")})
        position = _flat_position()

        repo.save_order_acceptance_transaction(order, reserved_cash, position)

        fetched_order = repo.get_order("order-1")
        assert fetched_order.status == OrderStatus.PENDING
        assert fetched_order.reserved_notional == Decimal("5000")
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")

    def test_persists_sell_acceptance_atomically(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        position = _position(reserved_quantity=Decimal("0"))
        repo.save_position(position)

        order = _order(side=OrderSide.SELL, status=OrderStatus.PENDING, reserved_price=Decimal("54000"), reserved_quantity=Decimal("0.1"))
        reserved_position = Position(**{**position.model_dump(), "reserved_quantity": Decimal("0.1")})

        repo.save_order_acceptance_transaction(order, repo.get_cash_balance("USDT"), reserved_position)

        assert repo.get_order("order-1").status == OrderStatus.PENDING
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0.1")

    def test_rollback_on_symbol_mismatch(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        order = _order(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        mismatched_position = _flat_position(symbol="ETHUSDT")

        with pytest.raises(ValueError):
            repo.save_order_acceptance_transaction(order, repo.get_cash_balance("USDT"), mismatched_position)

        assert repo.get_order("order-1") is None

    def test_rollback_leaves_no_partial_state(self, tmp_path):
        """Un id de orden duplicado (colisión con una fila ya existente por
        otro motivo) no debe dejar CashBalance/Position modificados."""
        repo = _repo(tmp_path)
        cash = _cash_balance(total_balance=Decimal("10000"))
        repo.save_cash_balance(cash)
        position = _flat_position()
        repo.save_position(position)

        # Simula un fallo forzando una excepción dentro de la transacción:
        # una Position con exchange/symbol distinto del de la Order.
        order = _order(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        bad_position = Position(**{**position.model_dump(), "symbol": "ETHUSDT"})
        bad_cash = CashBalance(**{**cash.model_dump(), "reserved_balance": Decimal("5005")})

        with pytest.raises(ValueError):
            repo.save_order_acceptance_transaction(order, bad_cash, bad_position)

        assert repo.get_order("order-1") is None
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")
        assert repo.get_position("Binance", "BTCUSDT").quantity == Decimal("0")


class TestSaveOrderCancellationTransaction:
    def test_persists_buy_cancellation_atomically(self, tmp_path):
        repo = _repo(tmp_path)
        cash = _cash_balance(total_balance=Decimal("10000"), reserved_balance=Decimal("5005"))
        repo.save_cash_balance(cash)
        order = _order(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        repo.save_order(order)

        cancelled_order = Order(**{**order.model_dump(), "status": OrderStatus.CANCELLED, "cancellation_reason": "test"})
        released_cash = CashBalance(**{**cash.model_dump(), "reserved_balance": Decimal("0")})
        position = _flat_position()

        repo.save_order_cancellation_transaction(cancelled_order, released_cash, position)

        assert repo.get_order("order-1").status == OrderStatus.CANCELLED
        assert repo.get_order("order-1").cancellation_reason == "test"
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")

    def test_persists_sell_cancellation_atomically(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        position = _position(reserved_quantity=Decimal("0.1"))
        repo.save_position(position)
        order = _order(side=OrderSide.SELL, status=OrderStatus.PENDING, reserved_price=Decimal("54000"), reserved_quantity=Decimal("0.1"))
        repo.save_order(order)

        cancelled_order = Order(**{**order.model_dump(), "status": OrderStatus.CANCELLED, "cancellation_reason": "test"})
        released_position = Position(**{**position.model_dump(), "reserved_quantity": Decimal("0")})

        repo.save_order_cancellation_transaction(cancelled_order, repo.get_cash_balance("USDT"), released_position)

        assert repo.get_order("order-1").status == OrderStatus.CANCELLED
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0")

    def test_rollback_on_symbol_mismatch(self, tmp_path):
        repo = _repo(tmp_path)
        cash = _cash_balance(reserved_balance=Decimal("5005"))
        repo.save_cash_balance(cash)
        order = _order(
            status=OrderStatus.PENDING, reserved_price=Decimal("50000"),
            reserved_notional=Decimal("5000"), reserved_fee=Decimal("5"),
        )
        repo.save_order(order)

        cancelled_order = Order(**{**order.model_dump(), "status": OrderStatus.CANCELLED, "cancellation_reason": "test"})
        mismatched_position = _flat_position(symbol="ETHUSDT")
        released_cash = CashBalance(**{**cash.model_dump(), "reserved_balance": Decimal("0")})

        with pytest.raises(ValueError):
            repo.save_order_cancellation_transaction(cancelled_order, released_cash, mismatched_position)

        assert repo.get_order("order-1").status == OrderStatus.PENDING
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("5005")


# --- PNL ------------------------------------------------------------------

class TestRealizedPnl:
    def _seed_two_trades(self, repo):
        repo.save_order(_order(id="o1", exchange="Binance", symbol="BTCUSDT"))
        repo.save_order(_order(id="o2", exchange="Binance", symbol="ETHUSDT"))
        repo.save_execution(_execution(id="e1", order_id="o1", exchange="Binance", symbol="BTCUSDT"))
        repo.save_execution(_execution(id="e2", order_id="o2", exchange="Binance", symbol="ETHUSDT"))
        repo.save_trade(_trade(id="t1", exchange="Binance", symbol="BTCUSDT", exit_execution_id="e1", net_pnl=Decimal("100")))
        repo.save_trade(_trade(id="t2", exchange="Binance", symbol="ETHUSDT", exit_execution_id="e2", net_pnl=Decimal("50")))

    def test_global_sum(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed_two_trades(repo)
        assert repo.calculate_realized_pnl() == Decimal("150")

    def test_by_exchange(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed_two_trades(repo)
        assert repo.calculate_realized_pnl(exchange="Binance") == Decimal("150")

    def test_by_symbol(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed_two_trades(repo)
        assert repo.calculate_realized_pnl(symbol="BTCUSDT") == Decimal("100")

    def test_by_exchange_and_symbol(self, tmp_path):
        repo = _repo(tmp_path)
        self._seed_two_trades(repo)
        assert repo.calculate_realized_pnl(exchange="Binance", symbol="ETHUSDT") == Decimal("50")

    def test_exact_decimal_sum(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(net_pnl=Decimal("0.1")))
        repo.save_trade(_trade(id="trade-2", exit_execution_id="exec-1", net_pnl=Decimal("0.2")))
        assert repo.calculate_realized_pnl() == Decimal("0.3")

    def test_empty_when_no_trades(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.calculate_realized_pnl() == Decimal("0")


class TestCheckPositionPnlConsistency:
    def test_consistent_position(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(net_pnl=Decimal("394.6")))
        repo.save_position(_position(realized_pnl_to_date=Decimal("394.6")))
        assert repo.check_position_pnl_consistency("Binance", "BTCUSDT") is True

    def test_inconsistent_position(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(net_pnl=Decimal("394.6")))
        repo.save_position(_position(realized_pnl_to_date=Decimal("999")))
        assert repo.check_position_pnl_consistency("Binance", "BTCUSDT") is False

    def test_nonexistent_position_returns_false(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.check_position_pnl_consistency("Binance", "DOESNOTEXIST") is False

    def test_does_not_modify_position(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        repo.save_execution(_execution())
        repo.save_trade(_trade(net_pnl=Decimal("999")))
        position = _position(realized_pnl_to_date=Decimal("1"))
        repo.save_position(position)
        repo.check_position_pnl_consistency("Binance", "BTCUSDT")
        assert repo.get_position("Binance", "BTCUSDT").realized_pnl_to_date == Decimal("1")


# --- LIMIT ------------------------------------------------------------------

class TestLimitValidation:
    def test_none_means_unlimited(self, tmp_path):
        repo = _repo(tmp_path)
        for i in range(3):
            repo.save_order(_order(id=f"o{i}"))
        assert len(repo.fetch_orders(limit=None)) == 3

    def test_positive_limit_is_accepted(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_order(_order())
        assert len(repo.fetch_orders(limit=1)) == 1

    def test_zero_is_rejected(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(ValueError):
            repo.fetch_orders(limit=0)

    def test_negative_is_rejected(self, tmp_path):
        repo = _repo(tmp_path)
        with pytest.raises(ValueError):
            repo.fetch_orders(limit=-1)


# --- RECONCILIACIÓN (Etapa 6.8) --------------------------------------------

class TestFetchCashBalances:
    def test_empty_when_nothing_saved(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.fetch_cash_balances() == []

    def test_returns_all_currencies_saved(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(currency="USDT"))
        repo.save_cash_balance(_cash_balance(currency="BUSD", total_balance=Decimal("500")))
        balances = repo.fetch_cash_balances()
        assert {b.currency for b in balances} == {"USDT", "BUSD"}

    def test_decimal_round_trip_exact(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(total_balance=Decimal("10000.123456789")))
        balances = repo.fetch_cash_balances()
        assert balances[0].total_balance == Decimal("10000.123456789")


class TestReconciliationAuditRecord:
    def test_save_and_persist_dry_run_record(self, tmp_path):
        repo = _repo(tmp_path)
        record = _audit_record(dry_run=True, success=True, issue_count=2, repaired_count=0)
        repo.save_reconciliation_audit_record(record)

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            row = conn.execute(
                "SELECT id, dry_run, success, issue_count, repaired_count, error_message "
                "FROM paper_trading_reconciliation_audit WHERE id = ?",
                ("audit-1",),
            ).fetchone()
        finally:
            conn.close()
        assert row == ("audit-1", 1, 1, 2, 0, None)

    def test_save_failure_record_with_error_message(self, tmp_path):
        repo = _repo(tmp_path)
        record = _audit_record(id="audit-fail", dry_run=False, success=False, error_message="boom")
        repo.save_reconciliation_audit_record(record)

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            row = conn.execute(
                "SELECT success, error_message FROM paper_trading_reconciliation_audit WHERE id = ?",
                ("audit-fail",),
            ).fetchone()
        finally:
            conn.close()
        assert row == (0, "boom")

    def test_audit_table_is_insert_only_duplicate_id_fails(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_reconciliation_audit_record(_audit_record(id="dup"))
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_reconciliation_audit_record(_audit_record(id="dup"))

    def test_report_json_and_operations_json_round_trip(self, tmp_path):
        repo = _repo(tmp_path)
        record = _audit_record(report_json='{"a": 1}', operations_json='[{"b": 2}]')
        repo.save_reconciliation_audit_record(record)

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            row = conn.execute(
                "SELECT report_json, operations_json FROM paper_trading_reconciliation_audit WHERE id = ?",
                ("audit-1",),
            ).fetchone()
        finally:
            conn.close()
        assert row == ('{"a": 1}', '[{"b": 2}]')


class TestSaveReconciliationTransaction:
    def test_updates_cash_balances_and_positions_atomically(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("100")))
        repo.save_position(_position(reserved_quantity=Decimal("0.05")))

        corrected_cash = CashBalance(**{**_cash_balance().model_dump(), "reserved_balance": Decimal("0")})
        corrected_position = Position(**{**_position().model_dump(), "reserved_quantity": Decimal("0")})
        audit_record = _audit_record(id="audit-repair", dry_run=False, repaired_count=2)

        repo.save_reconciliation_transaction(
            cash_balances=[corrected_cash], positions=[corrected_position], audit_record=audit_record,
        )

        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")
        assert repo.get_position("Binance", "BTCUSDT").reserved_quantity == Decimal("0")
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            row = conn.execute(
                "SELECT id FROM paper_trading_reconciliation_audit WHERE id = ?", ("audit-repair",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None

    def test_never_touches_orders_executions_or_trades(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        repo.save_order(_order())
        repo.save_execution(_execution())

        corrected_cash = CashBalance(**{**_cash_balance().model_dump(), "reserved_balance": Decimal("0")})
        repo.save_reconciliation_transaction(
            cash_balances=[corrected_cash], positions=[], audit_record=_audit_record(id="audit-x"),
        )

        assert repo.get_order("order-1") is not None
        assert repo.fetch_executions_by_order("order-1") != []

    def test_rollback_on_failure_leaves_no_partial_write(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance(reserved_balance=Decimal("100")))
        corrected_cash = CashBalance(**{**_cash_balance().model_dump(), "reserved_balance": Decimal("0")})

        def _boom(conn, audit_record):
            raise RuntimeError("simulated audit failure")

        monkeypatch.setattr(SQLitePaperTradingRepository, "_insert_reconciliation_audit", staticmethod(_boom))

        with pytest.raises(RuntimeError):
            repo.save_reconciliation_transaction(
                cash_balances=[corrected_cash], positions=[], audit_record=_audit_record(),
            )

        # El rollback deja reserved_balance sin corregir (no queda a medio aplicar).
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("100")


class TestReconciliationAuditMigration:
    def test_init_creates_audit_table_idempotently(self, tmp_path):
        repo = _repo(tmp_path)
        repo.init()
        repo.init()
        repo.save_reconciliation_audit_record(_audit_record())
        assert repo.fetch_cash_balances() == []  # tabla nueva, sin datos previos


# --- INSPECCIÓN AUTOMATIZADA (Etapa 6.9) -----------------------------------

class TestInspectionRunMigration:
    def test_init_creates_inspection_tables_idempotently(self, tmp_path):
        repo = _repo(tmp_path)
        repo.init()
        repo.init()
        repo.save_inspection_run_transaction(_inspection_run(), [])
        assert repo.get_latest_inspection_run().id == "run-1"

    def test_indexes_exist(self, tmp_path):
        repo = _repo(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        try:
            index_names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' "
                    "AND tbl_name IN ('paper_trading_inspection_runs', 'paper_trading_inspection_alerts')"
                ).fetchall()
            }
        finally:
            conn.close()
        assert "idx_paper_trading_inspection_runs_started_at" in index_names
        assert "idx_paper_trading_inspection_alerts_run_id" in index_names
        assert "idx_paper_trading_inspection_alerts_created_at" in index_names
        assert "idx_paper_trading_inspection_alerts_status" in index_names

    def test_foreign_key_run_id_enforced(self, tmp_path):
        repo = _repo(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO paper_trading_inspection_alerts "
                    "(id, run_id, alert_type, issue_key, issue_code, severity, title, message, "
                    "deduplication_key, status, delivery_attempts, last_error, created_at, delivered_at) "
                    "VALUES ('a1', 'nonexistent-run', 'NEW_ISSUE', NULL, NULL, NULL, 't', 'm', "
                    "'k1', 'PENDING', 0, NULL, ?, NULL)",
                    (_now().isoformat(),),
                )
                conn.commit()
        finally:
            conn.close()


class TestSaveInspectionRunTransaction:
    def test_persists_run_and_alerts_atomically(self, tmp_path):
        repo = _repo(tmp_path)
        run = _inspection_run()
        alert = _inspection_alert()
        repo.save_inspection_run_transaction(run, [alert])

        fetched_run = repo.get_latest_inspection_run()
        assert fetched_run.id == "run-1"
        assert fetched_run.report.issues[0].code == IssueCode.ORPHAN_CASH_RESERVATION

        fetched_alert = repo.get_inspection_alert_by_deduplication_key(alert.deduplication_key)
        assert fetched_alert.id == "alert-1"

    def test_rollback_on_duplicate_deduplication_key(self, tmp_path):
        repo = _repo(tmp_path)
        alert1 = _inspection_alert()
        repo.save_inspection_run_transaction(_inspection_run(), [alert1])

        run2 = _inspection_run(id="run-2")
        alert2 = _inspection_alert(id="alert-2", run_id="run-2", deduplication_key=alert1.deduplication_key)
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_inspection_run_transaction(run2, [alert2])

        assert repo.get_latest_inspection_run().id == "run-1"  # run-2 no se persistió (rollback)

    def test_unique_deduplication_key_constraint(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _inspection_alert()
        repo.save_inspection_run_transaction(_inspection_run(), [alert])
        run2 = _inspection_run(id="run-2")
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_inspection_run_transaction(
                run2, [_inspection_alert(id="alert-2", run_id="run-2", deduplication_key=alert.deduplication_key)],
            )

    def test_failed_run_with_null_report_json(self, tmp_path):
        repo = _repo(tmp_path)
        failed_run = _inspection_run(id="run-fail", success=False, report=None, error_message="boom")
        repo.save_inspection_run_transaction(failed_run, [])
        fetched = repo.get_latest_inspection_run()
        assert fetched.success is False
        assert fetched.report is None
        assert fetched.error_message == "boom"


class TestGetLatestInspectionRuns:
    def test_get_latest_successful_run(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_inspection_run_transaction(_inspection_run(id="run-1"), [])
        repo.save_inspection_run_transaction(_inspection_run(id="run-fail", success=False, report=None), [])
        latest_successful = repo.get_latest_successful_inspection_run()
        assert latest_successful.id == "run-1"

    def test_get_latest_run_regardless_of_success(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_inspection_run_transaction(_inspection_run(id="run-1"), [])
        repo.save_inspection_run_transaction(_inspection_run(id="run-fail", success=False, report=None), [])
        latest = repo.get_latest_inspection_run()
        assert latest.id == "run-fail"

    def test_returns_none_when_empty(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_latest_successful_inspection_run() is None
        assert repo.get_latest_inspection_run() is None

    def test_history_limit(self, tmp_path):
        repo = _repo(tmp_path)
        for i in range(3):
            repo.save_inspection_run_transaction(_inspection_run(id=f"run-{i}"), [])
        assert len(repo.fetch_inspection_runs(limit=2)) == 2
        assert len(repo.fetch_inspection_runs(limit=None)) == 3


class TestInspectionAlertDelivery:
    def test_fetch_pending_alerts(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _inspection_alert()
        repo.save_inspection_run_transaction(_inspection_run(), [alert])
        pending = repo.fetch_pending_inspection_alerts()
        assert [a.id for a in pending] == ["alert-1"]

    def test_transition_to_delivered(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _inspection_alert()
        repo.save_inspection_run_transaction(_inspection_run(), [alert])
        now = _now()
        repo.update_inspection_alert_delivery(
            alert_id="alert-1", status=AlertStatus.DELIVERED, delivery_attempts=1, last_error=None, delivered_at=now,
        )
        fetched = repo.get_inspection_alert_by_deduplication_key(alert.deduplication_key)
        assert fetched.status == AlertStatus.DELIVERED
        assert fetched.delivery_attempts == 1
        assert fetched.delivered_at is not None
        assert repo.fetch_pending_inspection_alerts() == []

    def test_transition_to_failed_with_error(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _inspection_alert()
        repo.save_inspection_run_transaction(_inspection_run(), [alert])
        repo.update_inspection_alert_delivery(
            alert_id="alert-1", status=AlertStatus.FAILED, delivery_attempts=3, last_error="boom", delivered_at=None,
        )
        fetched = repo.get_inspection_alert_by_deduplication_key(alert.deduplication_key)
        assert fetched.status == AlertStatus.FAILED
        assert fetched.last_error == "boom"
        assert fetched.delivery_attempts == 3

    def test_get_by_deduplication_key_returns_none_if_missing(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_inspection_alert_by_deduplication_key("nonexistent") is None


class TestInspectionPersistenceAcrossRestart:
    def test_runs_and_alerts_survive_reinitialization(self, tmp_path):
        repo = _repo(tmp_path)
        alert = _inspection_alert()
        repo.save_inspection_run_transaction(_inspection_run(), [alert])
        repo.update_inspection_alert_delivery(
            alert_id="alert-1", status=AlertStatus.DELIVERED, delivery_attempts=1, last_error=None, delivered_at=_now(),
        )

        restarted_repo = SQLitePaperTradingRepository(str(tmp_path / "test.db"))
        restarted_repo.init()
        run = restarted_repo.get_latest_inspection_run()
        assert run.id == "run-1"
        fetched_alert = restarted_repo.get_inspection_alert_by_deduplication_key(alert.deduplication_key)
        assert fetched_alert.status == AlertStatus.DELIVERED

    def test_does_not_change_operational_tables(self, tmp_path):
        repo = _repo(tmp_path)
        repo.save_cash_balance(_cash_balance())
        repo.save_order(_order())
        repo.save_inspection_run_transaction(_inspection_run(), [_inspection_alert()])
        assert repo.get_cash_balance("USDT").reserved_balance == Decimal("0")
        assert repo.get_order("order-1") is not None


# --- AISLAMIENTO ----------------------------------------------------------

class TestIsolation:
    def test_module_does_not_import_engines(self):
        import src.paper_trading.sqlite_repository as module
        source = open(module.__file__, encoding="utf-8").read()
        for forbidden in ("fill_engine", "position_engine", "pnl_engine", "risk_engine"):
            assert forbidden not in source

    def test_module_does_not_use_real_for_any_column(self):
        """Ninguna columna de este esquema usa REAL: todos los campos monetarios
        o de cantidad se guardan como TEXT (Decimal exacto, ver serialization.py)."""
        import src.paper_trading.sqlite_repository as module
        source = open(module.__file__, encoding="utf-8").read()
        assert " REAL" not in source
