"""One public, paginated feed across finance events, news judgments and market reports."""

from sqlalchemy import DateTime, String, and_, case, cast, func, literal, null, or_, select, union_all

from finance_analysis.core.time import coerce_aware_utc, day_bounds_utc  # pragma: allowlist secret
from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.news import NewsIntel
from finance_analysis.database.models.news_analysis import NewsAnalysis
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.session import DatabaseManager
from finance_analysis.market_calendar.events import source_payloads  # pragma: allowlist secret
from finance_analysis.timeline.cursor import TimelineCursor
from finance_analysis.timeline.dto import TimelineItem  # pragma: allowlist secret


class TimelineService:
    """Everyone sees the same feed; the timeline carries no user-owned content."""

    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def _projection(self, session, *, end_date=None, timezone_name, **filters):
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
                f.calendar_type.label("calendar_type"),
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
                cast(null(), String),
                literal("US"),
                a.importance,
                a.actionability,
                a.importance_score,
            ).join(n, n.id == a.news_intel_id),
            select(
                literal("report"),
                t.id,
                t.event_time,
                literal("analysis"),
                cast(null(), String),
                t.market,
                t.importance,
                t.actionability,
                literal(0),
            ),
        ).subquery()
        stmt = select(projection)
        if end_date is not None:
            stmt = stmt.where(projection.c.event_time < day_bounds_utc(end_date, timezone_name)[1])
        for key in ("market", "category", "calendar_type", "importance"):
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
    def _load_details(session, rows):
        """Hydrate only the selected page, with at most three source queries."""
        entries = {}
        for source, model in (("finance_event", FinanceEvent), ("report", TimelineEntry)):
            ids = [row["source_id"] for row in rows if row["source_type"] == source]
            if ids:
                for item in session.scalars(select(model).where(model.id.in_(ids))):
                    entries[(source, item.id)] = item
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
        if source == "report":
            item = entries[(source, row["source_id"])]
            base.update(
                title=item.title,
                summary=item.summary,
                symbol=item.symbol,
                related_symbols=item.related_symbols or [],
                event_type=item.entry_type,
                detail_type="report",
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
                    "counter_name": item.counter_name,
                    "market_session": item.market_session,
                    "reporting_period": item.reporting_period,
                    "currency": item.currency,
                    "provider": item.provider,
                    "source_providers": _source_providers(item),
                    "eps_estimate": item.eps_estimate,
                    "reported_eps": item.reported_eps,
                    "eps_surprise_pct": item.eps_surprise_pct,
                    "importance_reason": item.importance_reason,
                },
            )
        return TimelineItem(**base)


def _source_providers(event) -> list[str]:
    """Providers that actually contributed to a merged calendar event."""
    try:
        providers = sorted(source_payloads({"raw_payload_json": event.raw_payload_json}))
    except (TypeError, ValueError):
        providers = []
    return providers or ([event.provider] if event.provider else [])
