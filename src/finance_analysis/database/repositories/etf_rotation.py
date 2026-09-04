"""PostgreSQL repository boundary for ETF rotation bars and snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.etf_rotation import ETFMarketRotationSnapshot, ETFMomentumSnapshot
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.etf_rotation.universe import normalize_etf_market

SORT_FIELDS = {
    "composite_score": ETFMomentumSnapshot.composite_score,
    "entry_score": ETFMomentumSnapshot.entry_score,
    "momentum_score": ETFMomentumSnapshot.momentum_score,
    "ret_1d": ETFMomentumSnapshot.ret_1d,
    "ret_3d": ETFMomentumSnapshot.ret_3d,
    "ret_5d": ETFMomentumSnapshot.ret_5d,
    "ret_10d": ETFMomentumSnapshot.ret_10d,
    "ret_20d": ETFMomentumSnapshot.ret_20d,
}


class ETFRotationRepository:
    def __init__(self, market: str = "CN", db_manager=None):
        # Preserve the original ETFRotationRepository(db_manager) call style.
        if not isinstance(market, str):
            if db_manager is not None:
                raise TypeError("db_manager was provided twice")
            db_manager = market
            market = "CN"
        self.market = normalize_etf_market(market)
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def latest_daily_dates(self, codes: Iterable[str]) -> dict[str, date]:
        selected = sorted(set(codes))
        if not selected:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(Instrument.code, func.max(StockDaily.date))
                .join(StockDaily, StockDaily.instrument_id == Instrument.id)
                .where(Instrument.market == self.market, Instrument.code.in_(selected))
                .group_by(Instrument.code)
            ).all()
        return {str(code): latest for code, latest in rows if latest is not None}

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
        calendar_lookback_days: int = 180,
    ) -> list[Mapping[str, Any]]:
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
                        StockDaily.date.label("trade_date"),
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

    def historical_composite_ranks(self, trade_date: date, codes: Iterable[str]) -> dict[str, dict[int, int]]:
        selected = sorted(set(codes))
        if not selected:
            return {}
        with self.db.get_session() as session:
            dates = list(
                session.execute(
                    select(ETFMomentumSnapshot.trade_date)
                    .where(
                        ETFMomentumSnapshot.market == self.market,
                        ETFMomentumSnapshot.trade_date < trade_date,
                    )
                    .distinct()
                    .order_by(desc(ETFMomentumSnapshot.trade_date))
                    .limit(5)
                ).scalars()
            )
            if not dates:
                return {}
            rows = session.execute(
                select(Instrument.code, ETFMomentumSnapshot.trade_date, ETFMomentumSnapshot.rank)
                .join(Instrument, Instrument.id == ETFMomentumSnapshot.instrument_id)
                .where(
                    ETFMomentumSnapshot.market == self.market,
                    Instrument.market == self.market,
                    Instrument.code.in_(selected),
                    ETFMomentumSnapshot.trade_date.in_(dates),
                    ETFMomentumSnapshot.rank.is_not(None),
                )
            ).all()
        offsets = {snapshot_date: index + 1 for index, snapshot_date in enumerate(dates)}
        result: dict[str, dict[int, int]] = {}
        for code, snapshot_date, rank in rows:
            offset = offsets[snapshot_date]
            if offset in {1, 3, 5}:
                result.setdefault(str(code), {})[offset] = int(rank)
        return result

    def previous_candidate_codes(self, trade_date: date) -> set[str]:
        with self.db.get_session() as session:
            previous_date = session.execute(
                select(func.max(ETFMomentumSnapshot.trade_date)).where(
                    ETFMomentumSnapshot.market == self.market,
                    ETFMomentumSnapshot.trade_date < trade_date,
                )
            ).scalar_one()
            if previous_date is None:
                return set()
            return set(
                session.execute(
                    select(Instrument.code)
                    .join(ETFMomentumSnapshot, ETFMomentumSnapshot.instrument_id == Instrument.id)
                    .where(
                        ETFMomentumSnapshot.market == self.market,
                        ETFMomentumSnapshot.trade_date == previous_date,
                        ETFMomentumSnapshot.is_candidate.is_(True),
                    )
                ).scalars()
            )

    def upsert_market_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        record = {**snapshot, "generated_at": utc_now()}
        record.setdefault("diagnostics", {})
        with self.db.session_scope() as session:
            stmt = pg_insert(ETFMarketRotationSnapshot).values(record)
            excluded = stmt.excluded
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uix_etf_market_rotation_date_market",
                    set_={
                        column.name: getattr(excluded, column.name)
                        for column in ETFMarketRotationSnapshot.__table__.columns
                        if column.name not in {"id", "trade_date", "market"}
                    },
                )
            )

    def market_snapshot_by_date(self, trade_date: date) -> dict[str, Any] | None:
        with self.db.get_session() as session:
            snapshot = session.execute(
                select(ETFMarketRotationSnapshot).where(
                    ETFMarketRotationSnapshot.market == self.market,
                    ETFMarketRotationSnapshot.trade_date == trade_date,
                )
            ).scalar_one_or_none()
        if snapshot is None:
            return None
        return {column.name: getattr(snapshot, column.name) for column in ETFMarketRotationSnapshot.__table__.columns}

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
                raise ValueError(f"ETF Rotation symbols are not registered: {', '.join(missing)}")
            generated_at = utc_now()
            metadata_keys = {"code", "market", "name", "category", "theme", "risk_group"}
            column_names = {column.name for column in ETFMomentumSnapshot.__table__.columns}
            records = [
                {
                    **{key: value for key, value in item.items() if key not in metadata_keys and key in column_names},
                    "market": self.market,
                    "instrument_id": symbol_ids[str(item["code"])],
                    "generated_at": generated_at,
                }
                for item in snapshots
            ]
            stmt = pg_insert(ETFMomentumSnapshot).values(records)
            excluded = stmt.excluded
            immutable = {"id", "trade_date", "instrument_id"}
            updates = {
                column.name: getattr(excluded, column.name)
                for column in ETFMomentumSnapshot.__table__.columns
                if column.name not in immutable
            }
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uix_etf_momentum_snapshot_date_symbol",
                    set_=updates,
                )
            )
            session.execute(
                delete(ETFMomentumSnapshot).where(
                    ETFMomentumSnapshot.market == self.market,
                    ETFMomentumSnapshot.trade_date == records[0]["trade_date"],
                    ETFMomentumSnapshot.instrument_id.not_in(set(symbol_ids[code] for code in codes)),
                )
            )
        return len(records)

    def latest_trade_date(self) -> date | None:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(ETFMomentumSnapshot.trade_date)).where(ETFMomentumSnapshot.market == self.market)
            ).scalar_one()

    def available_trade_dates(self) -> list[date]:
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(ETFMomentumSnapshot.trade_date)
                    .where(ETFMomentumSnapshot.market == self.market)
                    .distinct()
                    .order_by(desc(ETFMomentumSnapshot.trade_date))
                ).scalars()
            )

    @staticmethod
    def _payload(snapshot: ETFMomentumSnapshot, code: str) -> dict[str, Any]:
        return {
            **{column.name: getattr(snapshot, column.name) for column in ETFMomentumSnapshot.__table__.columns},
            "code": code,
        }

    def snapshots_by_date(
        self,
        trade_date: date,
        *,
        sort_by: str = "composite_score",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sort_column = SORT_FIELDS.get(sort_by)
        if sort_column is None:
            raise ValueError(f"Unsupported ETF Rotation sort field: {sort_by}")
        query = (
            select(ETFMomentumSnapshot, Instrument.code)
            .join(Instrument, Instrument.id == ETFMomentumSnapshot.instrument_id)
            .where(
                ETFMomentumSnapshot.market == self.market,
                Instrument.market == self.market,
                ETFMomentumSnapshot.trade_date == trade_date,
            )
            .order_by(desc(sort_column).nulls_last(), desc(ETFMomentumSnapshot.momentum_score), Instrument.code)
        )
        if limit is not None:
            query = query.limit(limit)
        with self.db.get_session() as session:
            rows = session.execute(query).all()
            return [self._payload(snapshot, str(code)) for snapshot, code in rows]

    def latest_snapshots(self, *, sort_by: str = "composite_score", limit: int | None = None) -> list[dict[str, Any]]:
        latest = self.latest_trade_date()
        return [] if latest is None else self.snapshots_by_date(latest, sort_by=sort_by, limit=limit)

    def candidates_by_date(self, trade_date: date, *, limit: int = 5) -> list[dict[str, Any]]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(ETFMomentumSnapshot, Instrument.code)
                .join(Instrument, Instrument.id == ETFMomentumSnapshot.instrument_id)
                .where(
                    ETFMomentumSnapshot.market == self.market,
                    Instrument.market == self.market,
                    ETFMomentumSnapshot.trade_date == trade_date,
                    ETFMomentumSnapshot.action.in_(("BUY", "HOLD")),
                )
                .order_by(
                    ETFMomentumSnapshot.candidate_rank.asc().nulls_last(),
                    desc(ETFMomentumSnapshot.composite_score),
                    Instrument.code,
                )
                .limit(limit)
            ).all()
            return [self._payload(snapshot, str(code)) for snapshot, code in rows]

    def exits_by_date(self, trade_date: date) -> list[dict[str, Any]]:
        """Return every exit for the day; candidate display limits must never hide exits."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(ETFMomentumSnapshot, Instrument.code)
                .join(Instrument, Instrument.id == ETFMomentumSnapshot.instrument_id)
                .where(
                    ETFMomentumSnapshot.market == self.market,
                    Instrument.market == self.market,
                    ETFMomentumSnapshot.trade_date == trade_date,
                    ETFMomentumSnapshot.action == "EXIT",
                )
                .order_by(
                    ETFMomentumSnapshot.candidate_rank.asc().nulls_last(),
                    desc(ETFMomentumSnapshot.composite_score),
                    Instrument.code,
                )
            ).all()
            return [self._payload(snapshot, str(code)) for snapshot, code in rows]

    def previous_trade_date(self, trade_date: date) -> date | None:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(ETFMomentumSnapshot.trade_date)).where(
                    ETFMomentumSnapshot.market == self.market,
                    ETFMomentumSnapshot.trade_date < trade_date,
                )
            ).scalar_one()

    def snapshot_history(self, code: str, *, limit: int = 60) -> list[dict[str, Any]]:
        canonical = str(code).strip().upper()
        with self.db.get_session() as session:
            rows = session.execute(
                select(ETFMomentumSnapshot, Instrument.code)
                .join(Instrument, Instrument.id == ETFMomentumSnapshot.instrument_id)
                .where(
                    ETFMomentumSnapshot.market == self.market,
                    Instrument.market == self.market,
                    Instrument.code == canonical,
                )
                .order_by(desc(ETFMomentumSnapshot.trade_date))
                .limit(limit)
            ).all()
            return [self._payload(snapshot, str(row_code)) for snapshot, row_code in rows]


__all__ = ["ETFRotationRepository", "SORT_FIELDS"]
