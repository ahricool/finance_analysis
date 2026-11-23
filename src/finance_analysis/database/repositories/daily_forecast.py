"""Bounded reads of stored daily bars and atomic latest-forecast publication."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from math import isfinite

from sqlalchemy import and_, delete, func, insert, select, true
from sqlalchemy.orm import Session

from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.daily_forecast.models import DailyForecast, DailyForecastAccuracy, DailyForecastBar
from finance_analysis.database.models.daily_forecast import DailyForecastAccuracyState, DailyForecastSnapshot
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.session import DatabaseManager
from finance_analysis.market_review.trading_calendar import get_market_session_bounds
from finance_analysis.minute_forecast.models import AverageError, ForecastError, RecentErrors


def _settle_next_session(session: Session, market: str, as_of: date) -> None:
    snapshots = DailyForecastSnapshot
    previous = session.scalars(select(snapshots).where(snapshots.market == market, snapshots.anchor_date < as_of))
    candidates = [(snapshot, DailyForecastBar.model_validate(snapshot.bars[0])) for snapshot in previous]
    candidates = [(snapshot, bar) for snapshot, bar in candidates if bar.trade_date <= as_of]
    if not candidates:
        return
    dates = {bar.trade_date for _, bar in candidates}
    dates.update(snapshot.anchor_date for snapshot, _ in candidates)
    codes = [snapshot.symbol for snapshot, _ in candidates]
    closes = {
        (code, day): close
        for code, day, close in session.execute(
            select(Instrument.code, StockDaily.date, StockDaily.close)
            .join_from(Instrument, StockDaily)
            .where(Instrument.market == market, Instrument.code.in_(codes), StockDaily.date.in_(dates))
        )
    }
    state = DailyForecastAccuracyState
    existing = {row.symbol: row for row in session.scalars(
        select(state).where(state.market == market, state.symbol.in_(codes)),
    )}
    session_opens: dict[date, datetime | None] = {}
    for snapshot, bar in candidates:
        close = closes.get((snapshot.symbol, bar.trade_date))
        anchor = closes.get((snapshot.symbol, snapshot.anchor_date))
        if close is None or anchor is None or not all(
            isfinite(value) and value > 0 for value in (close, anchor, snapshot.anchor_close)
        ):
            continue
        if bar.trade_date not in session_opens:
            try:
                session_opens[bar.trade_date] = get_market_session_bounds(market.lower(), bar.trade_date)[0]
            except ValueError:
                # A previously scheduled exchange session can be canceled.
                session_opens[bar.trade_date] = None
        session_open = session_opens[bar.trade_date]
        issued = coerce_aware_utc(snapshot.generated_at)
        if session_open is None or issued is None or issued >= session_open:
            continue
        # Align the frozen prediction with today's forward-adjusted price basis.
        error = abs(bar.close * (anchor / snapshot.anchor_close) - close)
        baseline = abs(anchor - close)
        if not isfinite(error):
            continue

        row = existing.get(snapshot.symbol)
        if row is None:
            row = state(market=market, symbol=snapshot.symbol)
            session.add(row)
        elif row.target_date >= bar.trade_date:
            continue
        if (row.model, row.weights_revision) != (snapshot.model, snapshot.weights_revision):
            row.model, row.weights_revision = snapshot.model, snapshot.weights_revision
            row.sample_count, row.error_sum, row.baseline_error_sum = 0, 0.0, 0.0
        row.target_date, row.issued_at, row.actual_close = bar.trade_date, issued, close
        row.recent_error, row.recent_baseline_error = error, baseline
        row.sample_count += 1
        row.error_sum += error
        row.baseline_error_sum += baseline


def _accuracy_view(row: DailyForecastAccuracyState) -> DailyForecastAccuracy:
    issued = coerce_aware_utc(row.issued_at)
    assert issued is not None  # The stored issuance timestamp is non-nullable.
    return DailyForecastAccuracy(
        trading_date=row.target_date,
        recent=RecentErrors(issued_at=int(issued.timestamp() * 1000), rows=[
            ForecastError(step=1, close=row.actual_close, error=row.recent_error,
                          baseline_error=row.recent_baseline_error),
        ]),
        average=[AverageError(step=1, count=row.sample_count, mae=row.error_sum / row.sample_count,
                              baseline_mae=row.baseline_error_sum / row.sample_count)],
    )


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
            _settle_next_session(session, market, as_of)
            session.execute(delete(table).where(scope))
            if forecasts:
                rows = [dict(
                    forecast.model_dump(exclude={"accuracy", "bars"}),
                    market=market,
                    bars=[bar.model_dump(mode="json") for bar in forecast.bars],
                ) for forecast in forecasts]
                session.execute(insert(table), rows)
        return True

    def latest(self, market: str, symbol: str) -> DailyForecast | None:
        snapshot, state = DailyForecastSnapshot, DailyForecastAccuracyState
        query = select(snapshot, state).outerjoin(state, and_(
            state.market == snapshot.market, state.symbol == snapshot.symbol,
            state.model == snapshot.model, state.weights_revision == snapshot.weights_revision,
        )).where(snapshot.market == market, snapshot.symbol == symbol)
        with self.db.get_session() as session:
            row = session.execute(query).one_or_none()
            if row is None:
                return None
            forecast, accuracy = row
            result = DailyForecast.model_validate(forecast, from_attributes=True)
            return result.model_copy(update={"accuracy": _accuracy_view(accuracy)}) if accuracy is not None else result
