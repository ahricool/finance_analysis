"""Read-only views and atomic whole-cross-section upsert for industry observations."""

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.industry_strength import IndustryStrengthSnapshot as Snapshot

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

    def save(self, day, rows):
        if not rows or any(r["trade_date"] != day for r in rows):
            raise ValueError("A nonempty single-session cross-section is required")
        with self.db.session_scope() as session:
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
