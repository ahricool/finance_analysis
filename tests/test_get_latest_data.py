from datetime import date, timedelta

import pytest
from sqlalchemy import text

from finance_analysis.database import DatabaseManager
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository, StockRepository


@pytest.fixture()
def repository():
    db = DatabaseManager.get_instance()
    symbols = MarketDataSymbolRepository(db)
    symbol = symbols.get_by_code("AAPL.US")
    with db._engine.begin() as connection:
        connection.execute(text("DELETE FROM stock_daily WHERE symbol_id=:id"), {"id": symbol.id})
    yield StockRepository(db), symbol
    with db._engine.begin() as connection:
        connection.execute(text("DELETE FROM stock_daily WHERE symbol_id=:id"), {"id": symbol.id})


def _bar(day, close):
    return {"date": day, "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 100, "amount": None}


def test_get_latest_returns_count_and_descending_dates(repository):
    repo, symbol = repository
    today = date.today()
    repo.upsert_daily(symbol.id, [_bar(today - timedelta(days=i), 100 + i) for i in range(5)], "test", 10)
    rows = repo.get_latest("AAPL.US", days=2)
    assert len(rows) == 2
    assert rows[0].date > rows[1].date
    assert all(row.code == "AAPL.US" and row.market == "US" for row in rows)


def test_get_latest_is_scoped_by_canonical_symbol(repository):
    repo, symbol = repository
    repo.upsert_daily(symbol.id, [_bar(date.today(), 100)], "test", 10)
    assert len(repo.get_latest("AAPL.US")) == 1
    assert repo.get_latest("MSFT.US") == []


def test_priority_upsert_updates_equal_priority_and_rejects_lower(repository):
    repo, symbol = repository
    day = date.today()
    assert repo.upsert_daily(symbol.id, [_bar(day, 100)], "first", 50).inserted_rows == 1
    assert repo.upsert_daily(symbol.id, [_bar(day, 101)], "refresh", 50).updated_rows == 1
    assert repo.upsert_daily(symbol.id, [_bar(day, 99)], "lower", 10).skipped_lower_priority_rows == 1
    assert repo.get_latest("AAPL.US", 1)[0].close == 101
