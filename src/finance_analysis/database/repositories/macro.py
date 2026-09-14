"""Batch Universe membership and persisted date bounds; no market-data writes."""

from datetime import date

from sqlalchemy import func, select

from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.universe import Universe, UniverseMember
from finance_analysis.macro.config import MACRO_INSTRUMENTS, UNIVERSE_KEY
from finance_analysis.macro.models import MacroContext


class MacroRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def context(self, as_of: date | None = None, window: int | str = 21) -> MacroContext:
        """At most three queries, independent of the number of members.

        Dashboard uses the last 21 valid bars per member. Chart ranges use the
        latest N distinct stored session dates across the system macro universe.
        """
        with self.db.get_session() as session:
            members = session.execute(
                select(Instrument.id, Instrument.code, Instrument.name)
                .join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
                .join(Universe, Universe.id == UniverseMember.universe_id)
                .where(
                    Universe.key == UNIVERSE_KEY,
                    Universe.enabled.is_(True),
                    Instrument.market == "US",
                    Instrument.code.in_(MACRO_INSTRUMENTS),
                )
            ).all()
            names = {row.code: row.name for row in members}
            if not members:
                return MacroContext(names, {}, None, None)
            valid = (
                StockDaily.instrument_id.in_([row.id for row in members]),
                StockDaily.date <= (as_of or date.max),
                StockDaily.close > 0,
                StockDaily.close < float("inf"),
            )
            latest_by_id = dict(
                session.execute(
                    select(StockDaily.instrument_id, func.max(StockDaily.date))
                    .where(*valid)
                    .group_by(StockDaily.instrument_id)
                ).all()
            )
            latest = {row.code: latest_by_id[row.id] for row in members if row.id in latest_by_id}
            trade_date = max(latest.values(), default=None)
            if trade_date is None:
                return MacroContext(names, latest, None, None)
            if window == "ytd":
                start = trade_date.replace(month=1, day=1)
            elif window == 21:
                ranked = (
                    select(
                        StockDaily.date,
                        func.row_number()
                        .over(partition_by=StockDaily.instrument_id, order_by=StockDaily.date.desc())
                        .label("rn"),
                    )
                    .where(*valid)
                    .subquery()
                )
                start = session.scalar(select(func.min(ranked.c.date)).where(ranked.c.rn <= 21))
            else:
                dates = (
                    select(StockDaily.date)
                    .where(*valid)
                    .distinct()
                    .order_by(StockDaily.date.desc())
                    .limit(int(window))
                    .subquery()
                )
                start = session.scalar(select(func.min(dates.c.date)))
            return MacroContext(names, latest, trade_date, start)
