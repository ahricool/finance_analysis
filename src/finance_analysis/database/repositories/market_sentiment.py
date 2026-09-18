"""Atomic source + aggregate publication, including chronological dependent rebuilds."""

from datetime import date
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select, text

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.market_sentiment import MarketSentimentSnapshot as Snapshot
from finance_analysis.database.models.market_sentiment import MarketSentimentSourceSnapshot as Source
from finance_analysis.market_sentiment.calculator import calculate, normalized
from finance_analysis.market_sentiment.calendar import sessions_through
from finance_analysis.market_sentiment.config import SentimentConfig


class MarketSentimentRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def dates(self):
        with self.db.get_session() as session:
            return list(session.scalars(select(Snapshot.trade_date).order_by(Snapshot.trade_date.desc())))

    def overview(self, day=None):
        with self.db.get_session() as session:
            query = select(Snapshot).order_by(Snapshot.trade_date.desc()).limit(1)
            if day is not None:
                query = query.where(Snapshot.trade_date == day)
            row = session.scalar(query)
            return row.payload if row else None

    def history(self, days):
        with self.db.get_session() as session:
            return {
                r.trade_date: r.payload for r in session.scalars(select(Snapshot).where(Snapshot.trade_date.in_(days)))
            }

    def source(self, day, kind):
        with self.db.get_session() as session:
            row = session.scalar(select(Source).where(Source.trade_date == day, Source.source_kind == kind))
            return self._source(row) if row else None

    def ladder(self, as_of=None):
        with self.db.get_session() as session:
            query = select(Source).where(Source.source_kind == "ladder")
            if as_of is not None:
                query = query.where(Source.trade_date <= as_of)
            row = session.scalar(query.order_by(Source.trade_date.desc()).limit(1))
            return self._source(row) if row else None

    @staticmethod
    def _source(row):
        return {
            "trade_date": row.trade_date,
            "requested_trade_date": row.requested_trade_date,
            "source_kind": row.source_kind,
            "source_timestamp": row.source_timestamp,
            "fetched_at": row.fetched_at,
            "total": row.total,
            "item_count": row.item_count,
            "quality": row.quality,
            **row.payload,
        }

    def publish(self, day, sources, errors, config=SentimentConfig()):
        core = sources.get("limit_up")
        if (
            core is None
            or not core.quality.get("complete")
            or core.requested_trade_date != day
            or core.total != len(core.items)
            or len({r["thscode"] for r in core.items}) != core.total
        ):
            raise ValueError("A complete validated core pool is required; old result retained")
        with self.db.session_scope() as session:
            if session.bind.dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(956000001)"))
            # Replace all optional same-day observations too: never combine generations silently.
            session.execute(delete(Source).where(Source.trade_date == day, Source.source_kind != "ladder"))
            for kind, source in sources.items():
                source_day = date.fromisoformat(max(source.window["date_list"])) if kind == "ladder" else day
                session.execute(delete(Source).where(Source.trade_date == source_day, Source.source_kind == kind))
                items = [normalized(r) for r in source.items] if kind == "limit_up" else source.items
                session.add(
                    Source(
                        trade_date=source_day,
                        source_kind=kind,
                        requested_trade_date=source.requested_trade_date,
                        source_timestamp=source.source_timestamp,
                        fetched_at=source.fetched_at,
                        total=source.total,
                        item_count=len(items),
                        payload={"items": items, "window": source.window},
                        quality={**source.quality, **({"optional_errors": errors} if kind == "limit_up" else {})},
                    )
                )
            session.flush()
            all_sources = list(
                session.scalars(select(Source).where(Source.source_kind == "limit_up").order_by(Source.trade_date))
            )
            row_map = {r.trade_date: r.payload["items"] for r in all_sources}
            calculated = {}
            now = utc_now()
            # Recompute every dependent day chronologically in the SAME transaction.
            # No network and no partially published generations, including historical repairs.
            for source in all_sources:
                d = source.trade_date
                result = calculate(d, row_map[d], row_map, calculated, sessions_through(d, 21), config)
                calculated[d] = result
                if d < day:
                    continue
                supplements = {
                    r.source_kind: {
                        "total": r.total,
                        "source_timestamp": r.source_timestamp,
                        "fetched_at": r.fetched_at,
                    }
                    for r in session.scalars(
                        select(Source).where(
                            Source.trade_date == d, Source.source_kind.in_(["limit_down", "limit_break"])
                        )
                    )
                }
                result.update(
                    source_timestamp=source.source_timestamp,
                    fetched_at=source.fetched_at,
                    generated_at=now,
                    quality=source.quality,
                    supplements=supplements,
                )
                session.merge(
                    Snapshot(
                        trade_date=d,
                        rule_version=config.version,
                        state=result["state"],
                        generated_at=now,
                        payload=jsonable_encoder(result),
                    )
                )
            session.flush()
        return {"status": "completed", "trade_date": day.isoformat(), "optional_errors": errors}
