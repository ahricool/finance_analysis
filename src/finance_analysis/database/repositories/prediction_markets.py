"""Short transactions and compare-before-publish for shared prediction research."""

from datetime import timedelta

from sqlalchemy import func, or_, select, delete

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.prediction_markets import PredictionTag as Tag, PredictionEvent as Event
from finance_analysis.database.models.prediction_markets import PredictionInstrumentLink as Link
from finance_analysis.database.models.stock import Instrument
from finance_analysis.prediction_markets.rules import RULE_VERSION, decide, digest, tag_group, matching_version


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
                row = Event(event_id=data["event_id"], match_progress={})
                s.add(row)
            changed = row.semantic_hash != data["semantic_hash"]
            for key, value in data.items():
                # Missing upstream state must never erase an explicitly observed state.
                if key not in {"closed", "archived"} or value is not None:
                    setattr(row, key, value)
            row.rule_retained, row.rule_reason, row.rule_version = keep, reason, RULE_VERSION
            if manual:
                row.manual_retained = True
            row.retained = row.manual_retained if row.manual_retained is not None else keep
            if changed:
                row.match_status = "pending"
                row.retry_at, row.retry_count = None, 0
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

    def list_events(
        self, *, page=1, page_size=10, keyword="", tag_ids=(), closed=False, symbol=None, sort="updated", admin=False
    ):
        query = select(Event)
        if not admin:
            query = query.where(Event.retained.is_(True))
        if closed is not None:
            query = query.where(Event.closed.is_(True) if closed else Event.closed.is_not(True))
        if keyword:
            query = query.where(Event.title.ilike("%" + keyword.replace("%", r"\%").replace("_", r"\_") + "%"))
        if tag_ids:
            query = query.where(or_(*(Event.tag_ids.contains([t]) for t in tag_ids)))
        if symbol:
            query = (
                query.join(Link, Link.event_id == Event.id)
                .join(Instrument)
                .where(Instrument.code == symbol, Link.blocked.is_(False))
            )
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
                item = {k: v for k, v in values(row).items() if k not in {"match_progress"}}
                item["tags"] = [tags[t] for t in row.tag_ids if t in tags]
                item["url"] = "https://polymarket.com/event/" + row.slug
                item["links"] = [
                    dict(
                        symbol=i.code,
                        name=i.name,
                        relation_type=l.relation_type,
                        relevance=l.relevance,
                        reason=l.reason,
                        source=l.source,
                        blocked=l.blocked,
                        judged_at=l.judged_at,
                        stale=l.source == "automatic"
                        and (
                            l.input_version != matching_version(values(row), all_tags)
                            or row.match_status in {"pending", "failed"}
                        ),
                    )
                    for l, i in s.execute(
                        select(Link, Instrument)
                        .join(Instrument)
                        .where(Link.event_id == row.id, *([] if admin else [Link.blocked.is_(False)]))
                    )
                ]
                items.append(item)
            return dict(items=items, total=total, page=page, page_size=page_size)

    def profiles(self, focus=()):
        from finance_analysis.database.repositories.watch_list import WatchListRepo
        from finance_analysis.database.repositories.portfolio import PortfolioRepository

        symbols = set(WatchListRepo(self.db).get_codes()) | set(focus)
        symbols.update(code for code, _ in PortfolioRepository(self.db).monitored_symbols())
        with self.db.get_session() as s:
            instruments = list(
                s.scalars(
                    select(Instrument).where(
                        Instrument.code.in_(symbols),
                        Instrument.market.in_(["CN", "US"]),
                        Instrument.instrument_type.in_(["STOCK", "ETF"]),
                    )
                )
            )
            return self._public_profiles(s, instruments)

    @staticmethod
    def _public_profiles(session, instruments, lock=False):
        from finance_analysis.database.models.industry_strength import IndustryCatalog, IndustryMembership

        codes = [i.code for i in instruments if i.market == "CN"]
        industries = {}
        if codes:
            query = (
                select(IndustryMembership.stock_code, IndustryCatalog.industry_name)
                .join(IndustryCatalog, IndustryMembership.industry_code == IndustryCatalog.industry_code)
                .where(IndustryMembership.stock_code.in_(codes))
            )
            if lock:
                query = query.with_for_update(read=True)
            for code, name in session.execute(query):
                industries.setdefault(code, []).append(name)
        result = []
        for i in instruments:
            meta = i.instrument_metadata or {}
            classification = meta.get("classification") or {}
            industry = (
                industries.get(i.code, [])
                if i.market == "CN"
                else [classification[k] for k in ("sector", "industry") if isinstance(classification.get(k), str)]
            )
            aliases = meta.get("aliases", [])
            result.append(
                dict(
                    symbol=i.code,
                    name=i.name,
                    aliases=sorted(a for a in aliases if isinstance(a, str)) if isinstance(aliases, list) else [],
                    industries=sorted(set(industry)),
                )
            )
        return sorted(result, key=lambda p: p["symbol"])

    def mark_pending(self, profiles):
        """Discovery of public-pool changes never triggers LLM work in catalog sync."""
        with self.db.session_scope() as s:
            tags = [values(t) for t in s.scalars(select(Tag))]
            for row in s.scalars(select(Event).where(Event.retained.is_(True)).with_for_update()):
                if row.match_version != digest([profiles, matching_version(values(row), tags)]):
                    row.match_status = "pending"
                    row.retry_at = None
        counts = {}
        for event in self.all_events():
            counts[event["match_status"]] = counts.get(event["match_status"], 0) + 1
        return counts

    def publish_group(self, event_id, semantic_hash, version, profiles, associations):
        """Replace only this evaluated group. Manual rows and other groups survive."""
        with self.db.session_scope() as s:
            row = s.scalar(select(Event).where(Event.event_id == event_id).with_for_update())
            tags = [values(t) for t in s.scalars(select(Tag))]
            if row.semantic_hash != semantic_hash or not row.retained or matching_version(values(row), tags) != version:
                return False
            symbols = {p["symbol"]: p for p in profiles}
            instruments = {
                i.code: i
                for i in s.scalars(select(Instrument).where(Instrument.code.in_(symbols)).with_for_update(read=True))
            }
            current_profiles = self._public_profiles(s, list(instruments.values()), lock=True)
            if current_profiles != sorted(profiles, key=lambda p: p["symbol"]):
                return False
            answers = {a["symbol"]: a for a in associations}
            progress = dict(row.match_progress or {})
            for symbol, profile in symbols.items():
                link = s.scalar(
                    select(Link).where(Link.event_id == row.id, Link.instrument_id == instruments[symbol].id)
                )
                if link is None or (link.source == "automatic" and not link.blocked):
                    if symbol not in answers:
                        if link is not None:
                            s.delete(link)
                    else:
                        if link is None:
                            link = Link(event_id=row.id, instrument_id=instruments[symbol].id)
                            s.add(link)
                        for key in ("relation_type", "relevance", "reason"):
                            setattr(link, key, answers[symbol][key])
                        link.source, link.input_version, link.judged_at = "automatic", version, utc_now()
                progress[symbol] = {"version": version, "profile": digest(profile)}
            row.match_progress = progress
            row.match_status, row.match_error = "pending", None
            row.retry_at, row.retry_count = None, 0
            return True

    def finish_matching(self, event_id, semantic_hash, version, profiles, candidates):
        with self.db.session_scope() as s:
            row = s.scalar(select(Event).where(Event.event_id == event_id).with_for_update())
            tags = [values(t) for t in s.scalars(select(Tag))]
            if row.semantic_hash != semantic_hash or not row.retained or matching_version(values(row), tags) != version:
                return False
            progress = row.match_progress or {}
            if any(progress.get(p["symbol"]) != {"version": version, "profile": digest(p)} for p in candidates):
                return False
            valid_ids = select(Instrument.id).where(Instrument.code.in_([p["symbol"] for p in candidates]))
            s.execute(
                delete(Link).where(
                    Link.event_id == row.id,
                    Link.source == "automatic",
                    Link.blocked.is_(False),
                    or_(Link.input_version != version, Link.instrument_id.not_in(valid_ids)),
                )
            )
            count = s.scalar(
                select(func.count()).select_from(Link).where(Link.event_id == row.id, Link.blocked.is_(False))
            )
            row.match_status = "matched" if count else "no_match" if candidates else "no_candidates"
            row.match_version, row.match_error = digest([profiles, version]), None
            row.match_progress = {p["symbol"]: progress[p["symbol"]] for p in candidates}
            row.retry_at, row.retry_count = None, 0
            return True

    def fail_matching(self, event_id, semantic_hash, error, attempted_version=None):
        with self.db.session_scope() as s:
            row = s.scalar(select(Event).where(Event.event_id == event_id).with_for_update())
            if row.semantic_hash == semantic_hash:
                row.match_status, row.match_error = "failed", error[:200]
                if attempted_version is not None:
                    row.match_version = attempted_version
                row.retry_count += 1
                row.retry_at = utc_now() + timedelta(minutes=min(1440, 30 * 2 ** min(row.retry_count - 1, 6)))

    def retry(self, event_id=None):
        with self.db.session_scope() as s:
            query = select(Event).with_for_update()
            if event_id:
                query = query.where(Event.event_id == event_id)
            for row in s.scalars(query):
                row.retry_at, row.retry_count = None, 0
                row.match_status = "pending"

    def set_link(self, event_id, symbol, action, relation_type="direct", relevance="high", reason="人工关联"):
        with self.db.session_scope() as s:
            event = s.scalar(select(Event).where(Event.event_id == event_id).with_for_update())
            instrument = s.scalar(select(Instrument).where(Instrument.code == symbol))
            if event is None or instrument is None:
                raise ValueError("话题或证券主数据不存在")
            row = s.scalar(select(Link).where(Link.event_id == event.id, Link.instrument_id == instrument.id))
            if action == "restore":
                if row:
                    s.delete(row)
                progress = dict(event.match_progress or {})
                progress.pop(symbol, None)
                event.match_progress, event.match_status, event.retry_at = progress, "pending", None
                return
            if row is None:
                row = Link(event_id=event.id, instrument_id=instrument.id)
                s.add(row)
            row.source, row.blocked = "manual", action == "block"
            row.relation_type, row.relevance, row.reason = relation_type, relevance, reason
            row.input_version, row.judged_at = "manual", utc_now()
