"""
Pruebas para el stub src/paper_trading/postgres_repository.py
(PostgresPaperTradingRepository).

No está implementado a propósito (ver docstring del archivo): estas
pruebas solo confirman que cumple la interfaz PaperTradingRepository y
que, si se usa antes de tiempo, falla de forma clara en vez de
silenciosa. Mismo patrón que tests/test_ai_postgres_stub.py y
tests/test_signals_postgres_stub.py. No se abre ninguna conexión real
ni se agrega ninguna dependencia de PostgreSQL.
"""

import pytest

from src.paper_trading.base import PaperTradingRepository
from src.paper_trading.postgres_repository import PostgresPaperTradingRepository


def _repo() -> PostgresPaperTradingRepository:
    return PostgresPaperTradingRepository(connection_url="postgresql://example")


def test_implements_the_repository_interface():
    assert isinstance(_repo(), PaperTradingRepository)


def test_constructor_only_stores_the_url_without_connecting():
    repo = _repo()
    assert repo.connection_url == "postgresql://example"


@pytest.mark.parametrize("method_name, args", [
    ("init", ()),
    ("save_order", (None,)),
    ("get_order", ("order-1",)),
    ("fetch_orders", ()),
    ("save_execution", (None,)),
    ("fetch_executions_by_order", ("order-1",)),
    ("fetch_executions", ()),
    ("save_trade", (None,)),
    ("fetch_trades", ()),
    ("save_position", (None,)),
    ("get_position", ("Binance", "BTCUSDT")),
    ("fetch_positions", ()),
    ("save_cash_balance", (None,)),
    ("get_cash_balance", ()),
    ("save_portfolio_snapshot", (None,)),
    ("fetch_portfolio_history", ()),
    ("save_pnl_snapshot", (None,)),
    ("fetch_pnl_history", ("Binance", "BTCUSDT")),
    ("save_fill_transaction", (None, None, None, None)),
    ("calculate_realized_pnl", ()),
    ("check_position_pnl_consistency", ("Binance", "BTCUSDT")),
])
def test_every_method_raises_not_implemented(method_name, args):
    repo = _repo()
    method = getattr(repo, method_name)
    with pytest.raises(NotImplementedError):
        method(*args)
