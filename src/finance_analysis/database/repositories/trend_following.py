"""Batch database access for Trend Following daily data and snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary

SORT_FIELDS = {
    "alpha_score": TrendFollowingSnapshot.alpha_score,
    "trend_score": TrendFollowingSnapshot.trend_score,
    "rs_score": TrendFollowingSnapshot.rs_score,
    "breakout_score": TrendFollowingSnapshot.breakout_score,
    "rank": TrendFollowingSnapshot.rank,
}
MEANINGFUL_STATES = {"CANDIDATE", "ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE", "EXIT"}
ACTIVE_POSITION_STATES = {"ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE"}


class TrendFollowingRepository:
    def __init__(self, market: str, db_manager: Any = None) -> None:
        self.market = str(market).upper()
        if self.market not in {"CN", "US"}:
            raise ValueError("Trend Following market must be CN or US")
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def latest_daily_date(self, code: str) -> date | None:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(StockDaily.date))
                .join(Instrument, Instrument.id == StockDaily.instrument_id)
                .where(Instrument.market == self.market, Instrument.code == code)
            ).scalar_one()

    def daily_codes_on_date(self, codes: Iterable[str], trade_date: date) -> set[str]:
        selected = sorted(set(codes))
        if not selected:
            return set()
        with self.db.get_session() as session:
            return set(
                session.execute(
                    select(Instrument.code)
                    .join(StockDaily, StockDaily.instrument_id == Instrument.id)
                    .where(
                        Instrument.market == self.market,
                        Instrument.code.in_(selected),
                        StockDaily.date == trade_date,
                    )
                ).scalars()
            )

    def load_daily_history(
        self,
        codes: Iterable[str],
        trade_date: date,
        *,
        calendar_lookback_days: int,
    ) -> list[Mapping[str, Any]]:
        """Load all required forward-adjusted OHLCV in one query; never returns future bars."""
        selected = sorted(set(codes))
        if not selected:
            return []
        start = trade_date - timedelta(days=calendar_lookback_days)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(
                        Instrument.id.label("instrument_id"),
                        Instrument.code,
                        Instrument.name,
                        StockDaily.date.label("trade_date"),
                        StockDaily.open,
                        StockDaily.high,
                        StockDaily.low,
                        StockDaily.close,
                        StockDaily.volume,
                        StockDaily.amount,
                    )
                    .join(StockDaily, StockDaily.instrument_id == Instrument.id)
                    .where(
                        Instrument.market == self.market,
                        Instrument.code.in_(selected),
                        StockDaily.date.between(start, trade_date),
                    )
                    .order_by(Instrument.code, StockDaily.date)
                ).mappings()
            )

    def previous_snapshots(self, trade_date: date, codes: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Load each code's latest snapshot strictly before the requested date."""
        selected = sorted(set(codes))
        if not selected:
            return {}
        ranked = (
            select(
                TrendFollowingSnapshot.id.label("snapshot_id"),
                func.row_number()
                .over(
                    partition_by=TrendFollowingSnapshot.code,
                    order_by=desc(TrendFollowingSnapshot.trade_date),
                )
                .label("row_rank"),
            )
            .where(
                TrendFollowingSnapshot.market == self.market,
                TrendFollowingSnapshot.trade_date < trade_date,
                TrendFollowingSnapshot.code.in_(selected),
            )
            .subquery()
        )
        with self.db.get_session() as session:
            rows = session.execute(
                select(TrendFollowingSnapshot)
                .join(ranked, ranked.c.snapshot_id == TrendFollowingSnapshot.id)
                .where(ranked.c.row_rank == 1)
            ).scalars()
            return {row.code: self._snapshot_payload(row) for row in rows}

    def latest_snapshot_date(self) -> date | None:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(TrendFollowingSnapshot.trade_date)).where(TrendFollowingSnapshot.market == self.market)
            ).scalar_one()

    def snapshot_dates_between(self, start: date, end: date) -> list[date]:
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(TrendFollowingSnapshot.trade_date)
                    .where(
                        TrendFollowingSnapshot.market == self.market,
                        TrendFollowingSnapshot.trade_date.between(start, end),
                    )
                    .distinct()
                    .order_by(TrendFollowingSnapshot.trade_date)
                ).scalars()
            )

    def daily_dates_between(self, code: str, start: date, end: date) -> list[date]:
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockDaily.date)
                    .join(Instrument, Instrument.id == StockDaily.instrument_id)
                    .where(
                        Instrument.market == self.market,
                        Instrument.code == code,
                        StockDaily.date.between(start, end),
                    )
                    .order_by(StockDaily.date)
                ).scalars()
            )

    def upsert_snapshots(self, snapshots: list[dict[str, Any]]) -> int:
        if not snapshots:
            return 0
        codes = sorted({str(item["code"]) for item in snapshots})
        with self.db.session_scope() as session:
            symbol_ids = dict(
                session.execute(
                    select(Instrument.code, Instrument.id).where(
                        Instrument.market == self.market,
                        Instrument.code.in_(codes),
                    )
                ).all()
            )
            missing = sorted(set(codes) - set(symbol_ids))
            if missing:
                raise ValueError(f"Trend Following symbols are not registered: {', '.join(missing[:10])}")
            columns = {column.name for column in TrendFollowingSnapshot.__table__.columns}
            records = []
            for item in snapshots:
                record = {key: value for key, value in item.items() if key in columns and key != "id"}
                record.update(instrument_id=symbol_ids[item["code"]], generated_at=utc_now())
                records.append(record)
            stmt = pg_insert(TrendFollowingSnapshot).values(records)
            excluded = stmt.excluded
            immutable = {"id", "market", "trade_date", "code"}
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uix_trend_following_market_date_code",
                    set_={
                        column.name: getattr(excluded, column.name)
                        for column in TrendFollowingSnapshot.__table__.columns
                        if column.name not in immutable
                    },
                )
            )
        return len(records)

    def replace_day(
        self,
        trade_date: date,
        snapshots: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> int:
        """Atomically replace one complete market/date snapshot set and its summary."""
        codes = sorted({str(item["code"]) for item in snapshots})
        with self.db.session_scope() as session:
            symbol_ids = (
                dict(
                    session.execute(
                        select(Instrument.code, Instrument.id).where(
                            Instrument.market == self.market,
                            Instrument.code.in_(codes),
                        )
                    ).all()
                )
                if codes
                else {}
            )
            missing = sorted(set(codes) - set(symbol_ids))
            if missing:
                raise ValueError(f"Trend Following symbols are not registered: {', '.join(missing[:10])}")

            session.execute(
                delete(TrendFollowingSnapshot).where(
                    TrendFollowingSnapshot.market == self.market,
                    TrendFollowingSnapshot.trade_date == trade_date,
                )
            )
            snapshot_columns = {column.name for column in TrendFollowingSnapshot.__table__.columns}
            generated_at = utc_now()
            records = []
            next_snapshot_id = None
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                next_snapshot_id = (
                    int(session.execute(select(func.coalesce(func.max(TrendFollowingSnapshot.id), 0))).scalar_one()) + 1
                )
            for item in snapshots:
                record = {key: value for key, value in item.items() if key in snapshot_columns and key != "id"}
                record.update(instrument_id=symbol_ids[item["code"]], generated_at=generated_at)
                if next_snapshot_id is not None:
                    record["id"] = next_snapshot_id
                    next_snapshot_id += 1
                records.append(record)
            if records:
                session.execute(TrendFollowingSnapshot.__table__.insert(), records)

            session.execute(
                delete(TrendFollowingSummary).where(
                    TrendFollowingSummary.market == self.market,
                    TrendFollowingSummary.trade_date == trade_date,
                )
            )
            summary_columns = {column.name for column in TrendFollowingSummary.__table__.columns}
            summary_record = {key: value for key, value in summary.items() if key in summary_columns and key != "id"}
            summary_record["generated_at"] = generated_at
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                summary_record["id"] = (
                    int(session.execute(select(func.coalesce(func.max(TrendFollowingSummary.id), 0))).scalar_one()) + 1
                )
            session.execute(TrendFollowingSummary.__table__.insert().values(**summary_record))
        return len(records)

    def invalidate_from(self, trade_date: date) -> None:
        """Atomically invalidate this market's recursive state chain from a failed date."""
        with self.db.session_scope() as session:
            session.execute(
                delete(TrendFollowingSnapshot).where(
                    TrendFollowingSnapshot.market == self.market,
                    TrendFollowingSnapshot.trade_date >= trade_date,
                )
            )
            session.execute(
                delete(TrendFollowingSummary).where(
                    TrendFollowingSummary.market == self.market,
                    TrendFollowingSummary.trade_date >= trade_date,
                )
            )

    def upsert_summary(self, summary: dict[str, Any]) -> None:
        columns = {column.name for column in TrendFollowingSummary.__table__.columns}
        record = {key: value for key, value in summary.items() if key in columns and key != "id"}
        record["generated_at"] = utc_now()
        with self.db.session_scope() as session:
            stmt = pg_insert(TrendFollowingSummary).values(record)
            excluded = stmt.excluded
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uix_trend_following_summary_market_date",
                    set_={
                        column.name: getattr(excluded, column.name)
                        for column in TrendFollowingSummary.__table__.columns
                        if column.name not in {"id", "market", "trade_date"}
                    },
                )
            )

    def latest_trade_date(self) -> date | None:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(TrendFollowingSummary.trade_date)).where(TrendFollowingSummary.market == self.market)
            ).scalar_one()

    def available_trade_dates(self) -> list[date]:
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(TrendFollowingSummary.trade_date)
                    .where(TrendFollowingSummary.market == self.market)
                    .order_by(desc(TrendFollowingSummary.trade_date))
                ).scalars()
            )

    def previous_trade_date(self, trade_date: date) -> date | None:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(TrendFollowingSummary.trade_date)).where(
                    TrendFollowingSummary.market == self.market,
                    TrendFollowingSummary.trade_date < trade_date,
                )
            ).scalar_one()

    def summary_by_date(self, trade_date: date) -> dict[str, Any] | None:
        with self.db.get_session() as session:
            row = session.execute(
                select(TrendFollowingSummary).where(
                    TrendFollowingSummary.market == self.market,
                    TrendFollowingSummary.trade_date == trade_date,
                )
            ).scalar_one_or_none()
        return (
            None
            if row is None
            else {column.name: getattr(row, column.name) for column in TrendFollowingSummary.__table__.columns}
        )

    @staticmethod
    def _snapshot_payload(row: TrendFollowingSnapshot, name: str | None = None) -> dict[str, Any]:
        payload = {column.name: getattr(row, column.name) for column in TrendFollowingSnapshot.__table__.columns}
        if name is not None:
            payload["name"] = name
        return payload

    def snapshots_by_date(
        self, trade_date: date, *, sort_by: str = "alpha_score", limit: int | None = None
    ) -> list[dict]:
        column = SORT_FIELDS.get(sort_by)
        if column is None:
            raise ValueError(f"Unsupported Trend Following sort field: {sort_by}")
        order = column.asc() if sort_by == "rank" else desc(column).nulls_last()
        query = (
            select(TrendFollowingSnapshot, Instrument.name)
            .join(Instrument, Instrument.id == TrendFollowingSnapshot.instrument_id)
            .where(TrendFollowingSnapshot.market == self.market, TrendFollowingSnapshot.trade_date == trade_date)
            .order_by(order, TrendFollowingSnapshot.code)
        )
        if limit is not None:
            query = query.limit(limit)
        with self.db.get_session() as session:
            return [self._snapshot_payload(row, str(name)) for row, name in session.execute(query).all()]

    def candidates_by_date(self, trade_date: date, *, limit: int = 100) -> list[dict]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(TrendFollowingSnapshot, Instrument.name)
                .join(Instrument, Instrument.id == TrendFollowingSnapshot.instrument_id)
                .where(
                    TrendFollowingSnapshot.market == self.market,
                    TrendFollowingSnapshot.trade_date == trade_date,
                    or_(TrendFollowingSnapshot.state.in_(MEANINGFUL_STATES), TrendFollowingSnapshot.action == "ADD"),
                )
                .order_by(TrendFollowingSnapshot.rank, TrendFollowingSnapshot.code)
                .limit(limit)
            ).all()
            return [self._snapshot_payload(row, str(name)) for row, name in rows]

    def positions_by_date(self, trade_date: date) -> list[dict]:
        """Return the strategy's active theoretical positions for one exact market date."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(TrendFollowingSnapshot, Instrument.name)
                .join(Instrument, Instrument.id == TrendFollowingSnapshot.instrument_id)
                .where(
                    TrendFollowingSnapshot.market == self.market,
                    TrendFollowingSnapshot.trade_date == trade_date,
                    TrendFollowingSnapshot.state.in_(ACTIVE_POSITION_STATES),
                    TrendFollowingSnapshot.units > 0,
                )
                .order_by(desc(TrendFollowingSnapshot.alpha_score), TrendFollowingSnapshot.code)
            ).all()
            return [self._snapshot_payload(row, str(name)) for row, name in rows]

    def snapshot_history(self, code: str, *, limit: int, as_of: date | None = None) -> list[dict]:
        canonical = str(code).strip().upper()
        filters = [
            TrendFollowingSnapshot.market == self.market,
            TrendFollowingSnapshot.code == canonical,
        ]
        if as_of is not None:
            filters.append(TrendFollowingSnapshot.trade_date <= as_of)
        with self.db.get_session() as session:
            rows = session.execute(
                select(TrendFollowingSnapshot, Instrument.name)
                .join(Instrument, Instrument.id == TrendFollowingSnapshot.instrument_id)
                .where(*filters)
                .order_by(desc(TrendFollowingSnapshot.trade_date))
                .limit(limit)
            ).all()
            return [self._snapshot_payload(row, str(name)) for row, name in rows]


__all__ = ["TrendFollowingRepository"]
