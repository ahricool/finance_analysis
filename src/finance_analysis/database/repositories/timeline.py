"""Persistence of public market reports shown on the investment timeline."""

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
