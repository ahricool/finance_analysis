"""Contract universe and native confirmed daily candle persistence."""
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.database import DatabaseManager
from finance_analysis.database.models.contracts import FuturesContract, FuturesDailyBar, FuturesMetricSample


def contracts():
    with DatabaseManager.get_instance().session_scope() as session:
        rows = session.scalars(select(FuturesContract).order_by(FuturesContract.created_at, FuturesContract.symbol))
        return [{"symbol": row.symbol, "category": row.category, "underlying_symbol": row.underlying_symbol}
                for row in rows]


def forecast_symbols():
    from finance_analysis.database.models.minute_forecast import MinuteForecastPreference

    with DatabaseManager.get_instance().get_session() as session:
        return list(session.scalars(select(FuturesContract.symbol).join(
            MinuteForecastPreference, MinuteForecastPreference.symbol == FuturesContract.symbol,
        )))


def latest_daily(symbol):
    with DatabaseManager.get_instance().session_scope() as session:
        return session.scalar(select(func.max(FuturesDailyBar.timestamp)).where(FuturesDailyBar.symbol == symbol))


def daily_timestamps(symbol, start, end):
    with DatabaseManager.get_instance().session_scope() as session:
        return set(session.scalars(select(FuturesDailyBar.timestamp).where(
            FuturesDailyBar.symbol == symbol,
            FuturesDailyBar.timestamp >= start,
            FuturesDailyBar.timestamp <= end,
        )))


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


def save_samples(symbol, source, samples):
    if not samples:
        return
    with DatabaseManager.get_instance().session_scope() as session:
        statement = insert(FuturesMetricSample).values([
            {"symbol": symbol, "period": "5m", "timestamp": stamp, source: values}
            for stamp, values in samples.items()
        ])
        session.execute(statement.on_conflict_do_update(
            index_elements=["symbol", "period", "timestamp"], set_={source: statement.excluded[source]},
        ))


def metric_history(symbol, start, end, limit):
    model = FuturesMetricSample
    with DatabaseManager.get_instance().session_scope() as session:
        rows = session.scalars(select(model).where(
            model.symbol == symbol, model.period == "5m", model.timestamp.between(start, end),
        ).order_by(model.timestamp).limit(limit))
        return [{col.name: getattr(row, col.name) for col in model.__table__.columns} for row in rows]


def sample_times(symbol, source, start, end):
    model = FuturesMetricSample
    with DatabaseManager.get_instance().session_scope() as session:
        return set(session.scalars(select(model.timestamp).where(
            model.symbol == symbol, model.period == "5m", model.timestamp.between(start, end),
            getattr(model, source).is_not(None),
        )))
