"""Persistence of reports and explicitly owned notes."""

from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.session import DatabaseManager


class TimelineEntryRepo:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def create(self, **values):
        values["event_time"] = coerce_aware_utc(values["event_time"])

        def write(session):
            item = TimelineEntry(**values)
            session.add(item)
            session.flush()
            session.refresh(item)
            return item

        return self.db._run_write_transaction("timeline.create", write)

    def update_note(self, item_id, *, uid, **values):
        def write(session):
            item = session.get(TimelineEntry, item_id)
            if item is None or item.uid != uid or item.entry_type != "manual_note":
                return None
            for key, value in values.items():
                setattr(item, key, coerce_aware_utc(value) if key == "event_time" else value)
            session.flush()
            session.refresh(item)
            return item

        return self.db._run_write_transaction("timeline.update_note", write)

    def delete_note(self, item_id, *, uid):
        def write(session):
            item = session.get(TimelineEntry, item_id)
            if item is None or item.uid != uid or item.entry_type != "manual_note":
                return False
            session.delete(item)
            return True

        return self.db._run_write_transaction("timeline.delete_note", write)
