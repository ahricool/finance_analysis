"""Bounded batch reads and atomic, idempotent market snapshot persistence."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot
from finance_analysis.database.models.market_structure import MarketStructureSnapshot
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository


class MarketStructureRepository(TrendFollowingRepository):
    def etf_rankings(self, trade_date):
        model = ETFMomentumSnapshot
        dates = (
            select(model.trade_date)
            .where(model.market == self.market, model.trade_date <= trade_date)
            .distinct()
            .order_by(model.trade_date.desc())
            .limit(6)
            .scalar_subquery()
        )
        with self.db.get_session() as session:
            rows = session.execute(
                select(model.trade_date, model.instrument_id, model.rank).where(
                    model.market == self.market, model.trade_date.in_(dates)
                )
            )
            result = {}
            for day, code, rank in rows:
                result.setdefault(day, {})[code] = rank
            return result

    def save(self, payload):
        with self.db.session_scope() as session:
            statement = insert(MarketStructureSnapshot).values(**payload, updated_at=utc_now())
            session.execute(
                statement.on_conflict_do_update(
                    constraint="uix_market_structure_market_date",
                    set_={
                        key: getattr(statement.excluded, key)
                        for key in (*payload, "updated_at")
                        if key not in {"market", "trade_date"}
                    },
                )
            )

    def read(self, trade_date=None):
        model = MarketStructureSnapshot
        query = select(model).where(model.market == self.market)
        if trade_date is not None:
            query = query.where(model.trade_date == trade_date)
        with self.db.get_session() as session:
            row = session.execute(query.order_by(model.trade_date.desc()).limit(1)).scalar_one_or_none()
            return None if row is None else {c.name: getattr(row, c.name) for c in model.__table__.columns}
