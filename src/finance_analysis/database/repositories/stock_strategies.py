"""Atomic daily transitions and immutable shared simulation evidence."""

from copy import deepcopy

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.stock_strategies import (
    StockStrategyDay,
    StockStrategyLaunch,
    StockStrategyRun,
    StockStrategyState,
)
from finance_analysis.stock_strategies.engine import initial_state


def values(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns} if row is not None else None


def query_budget(session):
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET LOCAL statement_timeout = '45000'"))
        session.execute(text("SET LOCAL lock_timeout = '5000'"))


class StockStrategyRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def launch(self, day, market, freeze):
        with self.db.session_scope() as session:
            query_budget(session)
            session.execute(
                insert(StockStrategyLaunch)
                .values(id=1, launch_date=day, universes={}, created_at=utc_now())
                .on_conflict_do_nothing(index_elements=["id"])
            )
        with self.db.session_scope() as session:
            query_budget(session)
            row = session.scalar(select(StockStrategyLaunch).where(StockStrategyLaunch.id == 1).with_for_update())
            if market not in row.universes:
                row.universes = dict(row.universes, **{market: freeze()})
            return row.launch_date, deepcopy(row.universes[market])

    def initialize(self, spec, market, start):
        with self.db.session_scope() as session:
            query_budget(session)
            session.execute(
                insert(StockStrategyState)
                .values(
                    strategy_key=spec.key,
                    version=spec.version,
                    market=market,
                    start_date=start,
                    payload=initial_state(),
                    updated_at=utc_now(),
                )
                .on_conflict_do_nothing(index_elements=["strategy_key", "version", "market"])
            )

    def state(self, spec, market):
        with self.db.get_session() as session:
            query_budget(session)
            return values(session.get(StockStrategyState, (spec.key, spec.version, market)))

    def settle(self, spec, market, day, previous_day, calculate):
        """Never skip a session; state, ledger, metrics and success share one commit."""
        with self.db.session_scope() as session:
            query_budget(session)
            row = session.scalar(
                select(StockStrategyState)
                .where(
                    StockStrategyState.strategy_key == spec.key,
                    StockStrategyState.version == spec.version,
                    StockStrategyState.market == market,
                )
                .with_for_update()
            )
            if row.last_date and row.last_date >= day:
                return None
            if row.last_date != previous_day:
                raise ValueError("模拟账本不能跨过未结算交易日")
            if day < row.start_date:
                raise ValueError("不能在统一启动日期前回填模拟收益")
            state, snapshot = calculate(deepcopy(row.payload))
            row.payload, row.last_date, row.updated_at = state, day, utc_now()
            session.add(
                StockStrategyDay(strategy_key=spec.key, version=spec.version, market=market, trade_date=day, **snapshot)
            )
            self._attempt(session, spec, market, day, "success", None)
            return snapshot

    def _attempt(self, session, spec, market, day, status, reason):
        row = session.get(StockStrategyRun, (spec.key, spec.version, market, day))
        if row and row.status == "success":
            return
        if row:
            row.status, row.reason, row.updated_at = status, reason, utc_now()
            row.attempts += 1
        else:
            session.add(
                StockStrategyRun(
                    strategy_key=spec.key,
                    version=spec.version,
                    market=market,
                    trade_date=day,
                    status=status,
                    reason=reason,
                    attempts=1,
                    updated_at=utc_now(),
                )
            )

    def attempt(self, spec, market, day, status, reason):
        with self.db.session_scope() as session:
            query_budget(session)
            self._attempt(session, spec, market, day, status, reason)

    def latest(self, spec, market, *, include_universe=False):
        with self.db.get_session() as session:
            query_budget(session)
            criteria = (
                StockStrategyDay.strategy_key == spec.key,
                StockStrategyDay.version == spec.version,
                StockStrategyDay.market == market,
            )
            snapshot = session.scalar(
                select(StockStrategyDay).where(*criteria).order_by(StockStrategyDay.trade_date.desc()).limit(1)
            )
            attempt = session.scalar(
                select(StockStrategyRun)
                .where(
                    StockStrategyRun.strategy_key == spec.key,
                    StockStrategyRun.version == spec.version,
                    StockStrategyRun.market == market,
                )
                .order_by(StockStrategyRun.trade_date.desc())
                .limit(1)
            )
            launch = session.get(StockStrategyLaunch, 1) if include_universe else None
            universe = deepcopy((launch.universes or {}).get(market)) if launch else None
            return (
                values(snapshot),
                values(attempt),
                values(session.get(StockStrategyState, (spec.key, spec.version, market))),
                universe,
            )

    def history(self, spec, market, *, before=None, limit=100):
        with self.db.get_session() as session:
            query_budget(session)
            query = select(StockStrategyDay).where(
                StockStrategyDay.strategy_key == spec.key,
                StockStrategyDay.version == spec.version,
                StockStrategyDay.market == market,
            )
            if before:
                query = query.where(StockStrategyDay.trade_date < before)
            rows = list(session.scalars(query.order_by(StockStrategyDay.trade_date.desc()).limit(limit)))
            return [values(row) for row in rows]

    def curve(self, spec, market):
        """Only compact stored metrics; never recompute historical performance on GET."""
        columns = (
            "trade_date",
            "nav",
            "daily_return",
            "total_return",
            "cagr",
            "max_drawdown",
            "drawdown",
            "exposure",
            "benchmark_return",
        )
        with self.db.get_session() as session:
            query_budget(session)
            return [
                dict(r._mapping)
                for r in session.execute(
                    select(
                        *(getattr(StockStrategyDay, key) for key in columns),
                    )
                    .where(
                        StockStrategyDay.strategy_key == spec.key,
                        StockStrategyDay.version == spec.version,
                        StockStrategyDay.market == market,
                    )
                    .order_by(StockStrategyDay.trade_date)
                )
            ]

    def daily_groups(self, codes, start, end):
        """Stream scalar columns per instrument; never materialize a million ORM objects."""
        from itertools import groupby
        from finance_analysis.database.models.stock import Instrument, StockDaily

        fields = ("date", "open", "high", "low", "close", "volume", "amount")
        query = (
            select(Instrument.code, *(getattr(StockDaily, k) for k in fields))
            .join(
                StockDaily,
                StockDaily.instrument_id == Instrument.id,
            )
            .where(Instrument.code.in_(codes), StockDaily.date >= start, StockDaily.date <= end)
            .order_by(
                StockDaily.instrument_id,
                StockDaily.date,
            )
            .execution_options(yield_per=10000)
        )
        with self.db.get_session() as session:
            query_budget(session)
            for code, rows in groupby(session.execute(query).mappings(), key=lambda r: r["code"]):
                yield code, [{k: row[k] for k in fields} for row in rows]

    def market_context(self, market, day):
        from finance_analysis.database.models.etf_rotation import ETFMarketRotationSnapshot
        from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary

        with self.db.get_session() as session:
            query_budget(session)
            regimes = {
                r.trend_period: dict(
                    regime=r.market_regime,
                    score=r.market_score,
                    coverage=r.data_coverage,
                    generated_at=r.generated_at.isoformat(),
                )
                for r in session.scalars(
                    select(TrendFollowingSummary).where(
                        TrendFollowingSummary.market == market,
                        TrendFollowingSummary.trade_date == day,
                        TrendFollowingSummary.trend_period.in_((20, 60)),
                    )
                )
                if r.data_coverage >= 0.98
            }
            etf = session.scalar(
                select(ETFMarketRotationSnapshot).where(
                    ETFMarketRotationSnapshot.market == market, ETFMarketRotationSnapshot.trade_date == day
                )
            )
            trend60 = {
                r.code: dict(trend_score=r.trend_score, rs_score=r.rs_score)
                for r in session.execute(
                    select(
                        TrendFollowingSnapshot.code,
                        TrendFollowingSnapshot.trend_score,
                        TrendFollowingSnapshot.rs_score,
                    ).where(
                        TrendFollowingSnapshot.market == market,
                        TrendFollowingSnapshot.trade_date == day,
                        TrendFollowingSnapshot.trend_period == 60,
                    )
                )
            }
            return regimes, etf.regime if etf else None, etf.generated_at.isoformat() if etf else None, trend60

    def anchor_prices(self, codes, dates):
        """Small exact-date bridge for suspended holdings older than the warmup window."""
        from finance_analysis.database.models.stock import Instrument, StockDaily

        with self.db.get_session() as session:
            query_budget(session)
            return list(
                session.execute(
                    select(Instrument.code, StockDaily.date, StockDaily.close)
                    .join(
                        StockDaily,
                        StockDaily.instrument_id == Instrument.id,
                    )
                    .where(Instrument.code.in_(codes), StockDaily.date.in_(dates))
                )
            )
