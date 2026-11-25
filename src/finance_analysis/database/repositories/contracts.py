"""Contract universe and native confirmed daily candle persistence."""
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.database import DatabaseManager
from finance_analysis.database.models.contracts import FuturesContract, FuturesDailyBar


def contracts():
    with DatabaseManager.get_instance().session_scope() as session:
        return [{"symbol": row.symbol, "category": row.category} for row in
                session.scalars(select(FuturesContract).order_by(FuturesContract.created_at, FuturesContract.symbol))]


def latest_daily(symbol):
    with DatabaseManager.get_instance().session_scope() as session:
        return session.scalar(select(func.max(FuturesDailyBar.timestamp)).where(FuturesDailyBar.symbol == symbol))


def save_daily(symbol, bars):
    if not bars:
        return
    with DatabaseManager.get_instance().session_scope() as session:
        # Lock the universe row so concurrent removal cannot race this write.
        if session.scalar(select(FuturesContract).where(FuturesContract.symbol == symbol).with_for_update()) is None:
            return
        statement = insert(FuturesDailyBar).values([{"symbol": symbol, **bar} for bar in bars])
        session.execute(statement.on_conflict_do_update(
            index_elements=["symbol", "timestamp"],
            set_={key: getattr(statement.excluded, key)
                  for key in ("open", "high", "low", "close", "volume", "turnover")},
        ))


def daily(symbol, limit=2000):
    with DatabaseManager.get_instance().session_scope() as session:
        rows = session.scalars(select(FuturesDailyBar).where(FuturesDailyBar.symbol == symbol)
                               .order_by(FuturesDailyBar.timestamp.desc()).limit(limit)).all()
        return [{key: getattr(row, key) for key in
                 ("timestamp", "open", "high", "low", "close", "volume", "turnover")} for row in reversed(rows)]
