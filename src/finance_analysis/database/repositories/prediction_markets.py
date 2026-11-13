"""Short transactions for the shared prediction catalog."""

from sqlalchemy import func, or_, select

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.prediction_markets import PredictionTag as Tag, PredictionEvent as Event
from finance_analysis.prediction_markets.rules import RULE_VERSION, decide, tag_group


def values(row):
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


class Repository:
    def __init__(self, db=None):
        if db is None:
            from finance_analysis.database.session import DatabaseManager

            db = DatabaseManager.get_instance()
        self.db = db

    def tags(self, admin=False):
        with self.db.get_session() as s:
            query = select(Tag).order_by(Tag.label, Tag.tag_id)
            if not admin:
                query = query.where(Tag.visible.is_(True))
            rows = [values(t) for t in s.scalars(query)]
            from collections import Counter

            counts = Counter(t for ids in s.scalars(select(Event.tag_ids).where(Event.retained.is_(True))) for t in ids)
            for t in rows:
                t["event_count"] = counts[t["tag_id"]]
            return rows

    def upsert_tag(self, raw):
        with self.db.session_scope() as s:
            row = s.scalar(select(Tag).where(Tag.tag_id == str(raw["id"])).with_for_update())
            if row is None:
                row = Tag(tag_id=str(raw["id"]))
                s.add(row)
            row.slug, row.label = str(raw.get("slug") or ""), str(raw.get("label") or raw.get("slug") or raw["id"])
            row.rule_group = tag_group(row.slug, row.label)
            row.visible = row.manual_visible if row.manual_visible is not None else row.rule_group != "other"
            row.synced_at = utc_now()

    def set_tag(self, tag_id, visible):
        with self.db.session_scope() as s:
            row = s.scalar(select(Tag).where(Tag.tag_id == tag_id).with_for_update())
            if row is None:
                raise ValueError("标签尚未同步")
            row.manual_visible = visible
            row.visible = visible if visible is not None else row.rule_group != "other"
        self.reclassify()

    def reclassify(self):
        with self.db.session_scope() as s:
            tags = [values(t) for t in s.scalars(select(Tag))]
            for row in s.scalars(select(Event).with_for_update()):
                row.rule_retained, row.rule_reason = decide(values(row), tags)
                row.rule_version = RULE_VERSION
                row.retained = row.manual_retained if row.manual_retained is not None else row.rule_retained

    def upsert_event(self, data, tags, manual=False):
        with self.db.session_scope() as s:
            # Re-read current controls; caller snapshot may predate an administrator override.
            tags = [values(t) for t in s.scalars(select(Tag))]
            keep, reason = decide(data, tags)
            row = s.scalar(select(Event).where(Event.event_id == data["event_id"]).with_for_update())
            if row is None and not keep and not manual:
                return "excluded"
            new = row is None
            if new:
                row = Event(event_id=data["event_id"])
                s.add(row)
            for key, value in data.items():
                # Missing upstream state must never erase an explicitly observed state.
                if key not in {"closed", "archived"} or value is not None:
                    setattr(row, key, value)
            row.rule_retained, row.rule_reason, row.rule_version = keep, reason, RULE_VERSION
            if manual:
                row.manual_retained = True
            row.retained = row.manual_retained if row.manual_retained is not None else keep
            row.synced_at = utc_now()
            return "created" if new else "updated"

    def event(self, event_id):
        with self.db.get_session() as s:
            row = s.scalar(select(Event).where(Event.event_id == event_id))
            return values(row) if row else None

    def all_events(self):
        with self.db.get_session() as s:
            return [values(r) for r in s.scalars(select(Event).order_by(Event.id))]

    def set_event(self, event_id, retained):
        with self.db.session_scope() as s:
            row = s.scalar(select(Event).where(Event.event_id == event_id).with_for_update())
            if row is None:
                raise ValueError("话题尚未同步")
            row.manual_retained = retained
            row.retained = retained if retained is not None else row.rule_retained

    def list_events(self, *, page=1, page_size=10, keyword="", tag_ids=(), closed=False, sort="updated", admin=False):
        query = select(Event)
        if not admin:
            query = query.where(Event.retained.is_(True))
        if closed is not None:
            query = query.where(Event.closed.is_(True) if closed else Event.closed.is_not(True))
        if keyword:
            query = query.where(Event.title.ilike("%" + keyword.replace("%", r"\%").replace("_", r"\_") + "%"))
        if tag_ids:
            query = query.where(or_(*(Event.tag_ids.contains([t]) for t in tag_ids)))
        order = {
            "title": Event.title.asc(),
            "deadline": Event.end_at.asc().nulls_last(),
            "updated": Event.synced_at.desc(),
        }[sort]
        all_tags = self.tags(admin=True)
        tags = {t["tag_id"]: t for t in all_tags if t["visible"]}
        with self.db.get_session() as s:
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(
                query.order_by(order, Event.event_id).offset((page - 1) * page_size).limit(page_size)
            ).all()
            items = []
            for row in rows:
                item = values(row)
                item["tags"] = [tags[t] for t in row.tag_ids if t in tags]
                item["url"] = "https://polymarket.com/event/" + row.slug
                items.append(item)
            return dict(items=items, total=total, page=page, page_size=page_size)
