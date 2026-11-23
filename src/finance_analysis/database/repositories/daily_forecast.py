"""Bounded reads of stored daily bars and atomic latest-forecast publication."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, func, insert, select, true

from finance_analysis.daily_forecast.models import DailyForecast
from finance_analysis.database.models.daily_forecast import DailyForecastSnapshot
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.session import DatabaseManager


class DailyForecastRepository:
    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager.get_instance()

    def histories(self, market: str, ids: Sequence[int], as_of: date, limit: int) -> dict[str, list]:
        daily = StockDaily
        # The instrument/date index bounds each security's scan to the input window.
        history = (
            select(daily.date, daily.open, daily.high, daily.low, daily.close, daily.volume, daily.amount)
            .where(daily.instrument_id == Instrument.id, daily.date <= as_of)
            .order_by(daily.date.desc())
            .limit(limit)
            .correlate(Instrument)
            .lateral()
        )
        query = (
            select(Instrument.code, *history.c)
            .join_from(Instrument, history, true())
            .where(Instrument.market == market, Instrument.id.in_(ids))
            .order_by(Instrument.code, history.c.date)
        )
        result = defaultdict(list)
        with self.db.get_session() as session:
            for row in session.execute(query):
                result[row.code].append(row)
        return dict(result)

    def replace_market(self, market: str, as_of: date, forecasts: Sequence[DailyForecast]) -> bool:
        """Called while holding the market's forecast task lock."""
        table = DailyForecastSnapshot
        with self.db.session_scope() as session:
            scope = table.market == market
            latest = session.scalar(select(func.max(table.anchor_date)).where(scope))
            if latest is not None and latest > as_of:
                return False
            session.execute(delete(table).where(scope))
            if forecasts:
                rows = [dict(
                    forecast.model_dump(exclude={"bars"}),
                    market=market,
                    bars=[bar.model_dump(mode="json") for bar in forecast.bars],
                ) for forecast in forecasts]
                session.execute(insert(table), rows)
        return True

    def latest(self, market: str, symbol: str) -> DailyForecast | None:
        with self.db.get_session() as session:
            row = session.get(DailyForecastSnapshot, (market, symbol))
            return DailyForecast.model_validate(row, from_attributes=True) if row is not None else None
