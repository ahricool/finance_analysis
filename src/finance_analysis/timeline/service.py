"""One filtered, paginated feed across events, news judgments and reports."""

from datetime import timedelta

from sqlalchemy import DateTime, and_, case, cast, func, literal, or_, select, union_all

from finance_analysis.core.time import coerce_aware_utc, date_range_bounds_utc
from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.news import NewsIntel
from finance_analysis.database.models.news_analysis import NewsAnalysis
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.session import DatabaseManager
from finance_analysis.timeline.cursor import TimelineCursor
from finance_analysis.timeline.dto import TimelineItem, TimelineSummaryItem


class TimelineService:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def _projection(self, session, *, uid, start_date, end_date, timezone_name, **filters):
        start, end = date_range_bounds_utc(start_date, end_date, timezone_name)
        f, n, a, t = FinanceEvent, NewsIntel, NewsAnalysis, TimelineEntry
        critical_macro = (f.calendar_type == "macro") & (
            func.lower(f.title).like("%cpi%")
            | func.lower(f.title).like("%fomc%")
            | f.title.like("%非农%")
            | f.title.like("%消费者价格%")
            | f.title.like("%利率决议%")
        )
        fi = case(
            (critical_macro, "critical"),
            (f.importance_score >= 9, "critical"),
            (f.importance_score >= 7, "high"),
            (f.star >= 3, "high"),
            else_="normal",
        )
        # A date-only event belongs to the provider's market date, not midnight UTC.
        if session.bind.dialect.name == "postgresql":
            market_tz = case((f.market == "US", "America/New_York"), else_="Asia/Shanghai")
            all_day_time = func.timezone(market_tz, cast(f.event_date, DateTime))
        else:
            all_day_time = func.datetime(f.event_date)  # SQLite is used only by offline tests.
        event_time = func.coalesce(f.event_datetime, all_day_time)
        projection = union_all(
            select(
                literal("finance_event").label("source_type"),
                f.id.label("source_id"),
                event_time.label("event_time"),
                literal("event").label("category"),
                f.market,
                fi.label("importance"),
                literal("watch").label("actionability"),
                func.coalesce(f.importance_score, 0).label("importance_score"),
            ),
            select(
                literal("news"),
                a.id,
                func.coalesce(n.published_date, a.analyzed_at),
                literal("news"),
                literal("US"),
                a.importance,
                a.actionability,
                a.importance_score,
            ).join(n, n.id == a.news_intel_id),
            select(
                case((t.entry_type == "manual_note", "note"), else_="report"),
                t.id,
                t.event_time,
                case((t.entry_type == "manual_note", "note"), else_="analysis"),
                t.market,
                t.importance,
                t.actionability,
                literal(0),
            ).where(t.uid == uid),
        ).subquery()
        stmt = select(projection).where(projection.c.event_time >= start, projection.c.event_time < end)
        for key in ("market", "category", "importance", "actionability"):
            if filters.get(key):
                stmt = stmt.where(projection.c[key] == filters[key])
        return stmt.subquery()

    def list(self, *, cursor: TimelineCursor | None = None, limit=20, **query):
        with self.db.get_session() as session:
            feed = self._projection(session, **query)
            count = session.scalar(select(func.count()).select_from(feed))
            stmt = select(feed)
            if cursor is not None:
                stmt = stmt.where(
                    or_(
                        feed.c.event_time < cursor.event_time,
                        and_(feed.c.event_time == cursor.event_time, feed.c.source_type > cursor.source_type),
                        and_(
                            feed.c.event_time == cursor.event_time,
                            feed.c.source_type == cursor.source_type,
                            feed.c.source_id < cursor.source_id,
                        ),
                    )
                )
            rows = (
                session.execute(
                    stmt.order_by(
                        feed.c.event_time.desc(),
                        feed.c.source_type,
                        feed.c.source_id.desc(),
                    )
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = None
            if has_more:
                last = rows[-1]
                next_cursor = TimelineCursor(
                    coerce_aware_utc(last["event_time"]), last["source_type"], last["source_id"]
                ).encode()
            entries = self._load_details(session, rows)
            items = [self._detail(entries, row) for row in rows if (row["source_type"], row["source_id"]) in entries]
            return dict(items=items, total=count, limit=limit, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _local_day(session, feed, timezone_name):
        if session.bind.dialect.name == "postgresql":
            return func.date(func.timezone(timezone_name, feed.c.event_time))
        return func.date(feed.c.event_time)

    def summary(self, **query):
        with self.db.get_session() as session:
            feed = self._projection(session, **query)
            day = self._local_day(session, feed, query["timezone_name"])
            metrics = {"critical": feed.c.importance == "critical", "high": feed.c.importance == "high"}
            metrics.update(
                {category + "_count": feed.c.category == category for category in ("event", "news", "analysis", "note")}
            )
            rows = (
                session.execute(
                    select(
                        day.label("date"),
                        func.count().label("total"),
                        *[func.sum(case((condition, 1), else_=0)).label(name) for name, condition in metrics.items()],
                    )
                    .select_from(feed)
                    .group_by(day)
                )
                .mappings()
                .all()
            )
        counts = {str(row["date"]): {key: value for key, value in row.items() if key != "date"} for row in rows}
        return [
            TimelineSummaryItem(
                date=(query["start_date"] + timedelta(days=offset)).isoformat(),
                **counts.get((query["start_date"] + timedelta(days=offset)).isoformat(), {}),
            )
            for offset in range((query["end_date"] - query["start_date"]).days + 1)
        ]

    @staticmethod
    def _load_details(session, rows):
        """Hydrate only the selected page, with at most three source queries."""
        entries = {}
        for source, model in (("finance_event", FinanceEvent), ("report", TimelineEntry)):
            types = {source, "note"} if source == "report" else {source}
            ids = [row["source_id"] for row in rows if row["source_type"] in types]
            if ids:
                for item in session.scalars(select(model).where(model.id.in_(ids))):
                    kind = "note" if model is TimelineEntry and item.entry_type == "manual_note" else source
                    entries[(kind, item.id)] = item
        ids = [row["source_id"] for row in rows if row["source_type"] == "news"]
        if ids:
            for analysis, news in session.execute(
                select(NewsAnalysis, NewsIntel)
                .join(NewsIntel, NewsIntel.id == NewsAnalysis.news_intel_id)
                .where(NewsAnalysis.id.in_(ids))
            ):
                entries[("news", analysis.id)] = (analysis, news)
        return entries

    def _detail(self, entries, row):
        source = row["source_type"]
        base = dict(row)
        base["id"] = f"{source}:{row['source_id']}"
        base["event_time"] = coerce_aware_utc(base["event_time"])
        if source in {"report", "note"}:
            item = entries[(source, row["source_id"])]
            base.update(
                title=item.title,
                summary=item.summary,
                symbol=item.symbol,
                related_symbols=item.related_symbols or [],
                event_type=item.entry_type,
                detail_type="report" if source == "report" else "note",
                detail_payload={"content": item.content},
            )
        elif source == "news":
            analysis, news = entries[(source, row["source_id"])]
            payload = {
                key: getattr(analysis, key)
                for key in (
                    "importance_score",
                    "importance_reason",
                    "event_type",
                    "time_sensitivity",
                    "importance_confidence",
                    "impact",
                    "impact_score",
                    "impact_reason",
                    "impact_confidence",
                    "watch_points",
                    "risk_notes",
                    "related_symbols",
                    "model",
                    "prompt_version",
                    "analyzed_at",
                )
            }
            payload.update(title=news.title, source=news.source, published_at=news.published_date, url=news.url)
            base.update(
                title=news.title,
                summary=news.snippet or "",
                related_symbols=analysis.related_symbols or [],
                impact=analysis.impact,
                impact_score=analysis.impact_score,
                event_type=analysis.event_type,
                detail_type="news",
                detail_payload=payload,
            )
        else:
            item = entries[(source, row["source_id"])]
            base.update(
                title=item.title,
                summary=item.importance_reason or "",
                symbol=item.symbol,
                related_symbols=[item.symbol] if item.symbol else [],
                event_type=item.calendar_type,
                detail_type="event",
                detail_payload={
                    "content": item.content,
                    "all_day": item.event_datetime is None,
                    "event_date": item.event_date,
                    "importance_reason": item.importance_reason,
                },
            )
        return TimelineItem(**base)
