"""Read-only views and atomic whole-cross-section upsert for industry observations."""

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.industry_strength import IndustryStrengthSnapshot as Snapshot
from finance_analysis.database.models.industry_strength import IndustryStrengthConstituent as Constituent
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot as TrendSnapshot

SORT_FIELDS = {
    "strength_rank",
    "industry_name",
    "state",
    "strength_score",
    "rank_change_1d",
    "rank_change_3d",
    "rank_change_5d",
    "rs_5d",
    "rs_10d",
    "rs_20d",
    "momentum_acceleration_5d",
    "up_ratio",
    "above_ma5_ratio",
    "above_ma20_ratio",
    "turnover_ratio_5d",
}


def serialize(row):
    return {c.name: getattr(row, c.name) for c in Snapshot.__table__.columns}


class IndustryStrengthRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def stock_context(self, code):
        """Latest membership only; never infer historical membership from this table."""
        day = select(func.max(Snapshot.trade_date)).scalar_subquery()
        query = (
            select(Snapshot.industry_code, Snapshot.industry_name, Snapshot.trade_date,
                   Snapshot.state, Snapshot.strength_score, Snapshot.strength_rank,
                   Constituent.updated_at.label("members_observed_at"))
            .join(Constituent, Constituent.industry_code == Snapshot.industry_code)
            .where(Constituent.stock_code == code, Snapshot.trade_date == day)
            .order_by(Snapshot.strength_rank, Snapshot.industry_code)
        )
        with self.db.get_session() as session:
            return [dict(row) for row in session.execute(query).mappings()]

    def dates(self, end=None, limit=250):
        query = select(Snapshot.trade_date).distinct()
        if end is not None:
            query = query.where(Snapshot.trade_date <= end)
        with self.db.get_session() as session:
            return list(session.execute(query.order_by(Snapshot.trade_date.desc()).limit(limit)).scalars())

    def ranking(self, trade_date=None, sort_by="strength_rank", descending=None, limit=500):
        if sort_by not in SORT_FIELDS:
            raise ValueError("Unsupported industry sort field")
        field = getattr(Snapshot, sort_by)
        descending = sort_by not in {"strength_rank", "industry_name", "state"} if descending is None else descending
        day = trade_date if trade_date is not None else select(func.max(Snapshot.trade_date)).scalar_subquery()
        query = (
            select(Snapshot)
            .where(Snapshot.trade_date == day)
            .order_by((field.desc() if descending else field.asc()).nulls_last(), Snapshot.industry_code)
            .limit(limit)
        )
        with self.db.get_session() as session:
            return [serialize(r) for r in session.execute(query).scalars()]

    def history(self, end, codes=None, limit=20):
        dates = (
            select(Snapshot.trade_date)
            .distinct()
            .where(Snapshot.trade_date <= end)
            .order_by(Snapshot.trade_date.desc())
            .limit(limit)
            .scalar_subquery()
        )
        query = select(Snapshot).where(Snapshot.trade_date.in_(dates))
        if codes is not None:
            query = query.where(Snapshot.industry_code.in_(codes))
        with self.db.get_session() as session:
            return [
                serialize(r)
                for r in session.execute(query.order_by(Snapshot.trade_date, Snapshot.industry_code)).scalars()
            ]

    def latest_cn_trend_date(self):
        with self.db.get_session() as session:
            return session.scalar(select(func.max(TrendSnapshot.trade_date)).where(TrendSnapshot.market == "CN"))

    def latest_cn_trend_ranks(self, codes):
        """One query at the latest formal CN date, independent of the industry date."""
        codes = sorted(set(codes))
        if not codes:
            return {}
        latest = select(func.max(TrendSnapshot.trade_date)).where(TrendSnapshot.market == "CN").scalar_subquery()
        query = select(TrendSnapshot.code, TrendSnapshot.rank).where(
            TrendSnapshot.market == "CN", TrendSnapshot.trade_date == latest, TrendSnapshot.code.in_(codes)
        )
        with self.db.get_session() as session:
            return dict(session.execute(query).all())

    def constituents(self, code):
        query = select(Constituent).where(Constituent.industry_code == code).order_by(
            Constituent.change_pct.desc().nulls_last(), Constituent.stock_code
        )
        with self.db.get_session() as session:
            rows = session.execute(query).scalars().all()
            return {
                "industry_code": code,
                "updated_at": max((row.updated_at for row in rows), default=None),
                "constituent_count": len(rows),
                "daily_valid_count": sum(row.change_pct is not None for row in rows),
                "ma5_valid_count": sum(row.above_ma5 is not None for row in rows),
                "above_ma5_count": sum(row.above_ma5 is True for row in rows),
                "ma20_valid_count": sum(row.above_ma20 is not None for row in rows),
                "above_ma20_count": sum(row.above_ma20 is True for row in rows),
                "items": [{
                    "code": row.stock_code, "name": row.stock_name,
                    **{key: getattr(row, key) for key in (
                        "price", "change_pct", "volume", "amount", "above_ma5", "above_ma20", "trend_rank"
                    )},
                } for row in rows],
            }

    def save(self, day, rows, constituents=None):
        if not rows or any(r["trade_date"] != day for r in rows):
            raise ValueError("A nonempty single-session cross-section is required")
        with self.db.session_scope() as session:
            # A global lock serializes latest-table writers across snapshot dates.
            if constituents is not None:
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 954000000})
            # Serialize whole-date replacements; readers see either complete generation.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 954000000 + day.toordinal()})
            now = utc_now()
            statement = insert(Snapshot).values([{**r, "updated_at": now, "created_at": now} for r in rows])
            session.execute(
                statement.on_conflict_do_update(
                    constraint="uix_industry_strength_date_code",
                    set_={
                        c.name: getattr(statement.excluded, c.name)
                        for c in Snapshot.__table__.columns
                        if c.name not in {"id", "created_at", "trade_date", "industry_code"}
                    },
                )
            )
            session.execute(
                delete(Snapshot).where(
                    Snapshot.trade_date == day, Snapshot.industry_code.not_in([r["industry_code"] for r in rows])
                )
            )
            if constituents is not None:
                session.execute(delete(Constituent))
                if constituents:
                    # Executemany avoids a single enormous multi-VALUES parameter list.
                    session.execute(Constituent.__table__.insert(), [
                        {**row, "updated_at": now} for row in constituents
                    ])
