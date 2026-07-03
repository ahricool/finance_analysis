from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models import CalendarEntry, FinanceEvent
from finance_analysis.database.repositories.calendar import CalendarRepo
from finance_analysis.database.repositories.market_calendar_event import MarketCalendarEventRepo


class _SQLiteDB:
    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:")
        CalendarEntry.__table__.create(self.engine)
        FinanceEvent.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session


def test_calendar_entries_are_filtered_and_paginated_by_category():
    db = _SQLiteDB()
    now = datetime(2026, 6, 25, 4, tzinfo=timezone.utc)
    with db.get_session() as session:
        session.add_all(
            [
                CalendarEntry(uid=7, time=now, title="A1", type="scheduled_a_share_intraday"),
                CalendarEntry(uid=7, time=now, title="A2", type="a_share_intraday_signal"),
                CalendarEntry(uid=7, time=now, title="US", type="scheduled_us_premarket"),
                CalendarEntry(uid=7, time=now, title="News", type="scheduled_us_premarket_news"),
                CalendarEntry(uid=7, time=now, title="Manual", type="manual_note"),
                CalendarEntry(uid=7, time=now, title="No type", type=None),
                CalendarEntry(uid=8, time=now, title="Other user", type="scheduled_a_share_intraday"),
            ]
        )
        session.commit()

    repo = CalendarRepo(db=db)
    first_page, total = repo.list_by_date_paginated(
        date(2026, 6, 25), uid=7, category="a_share", page=1, limit=1
    )
    second_page, _ = repo.list_by_date_paginated(
        date(2026, 6, 25), uid=7, category="a_share", page=2, limit=1
    )
    other, other_total = repo.list_by_date_paginated(
        date(2026, 6, 25), uid=7, category="other", page=1, limit=20
    )

    assert total == 2
    assert len(first_page) == 1
    assert len(second_page) == 1
    assert {first_page[0].title, second_page[0].title} == {"A1", "A2"}
    assert other_total == 2
    assert {item.title for item in other} == {"Manual", "No type"}


def test_finance_events_are_paginated_after_priority_sorting():
    db = _SQLiteDB()
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    with db.get_session() as session:
        session.add_all(
            [
                FinanceEvent(
                    provider="manual",
                    event_key="event-low",
                    calendar_type="macro",
                    market="US",
                    event_date=date(2026, 6, 20),
                    title="Low priority",
                    content="",
                    importance_score=3,
                    first_seen_at=now,
                    last_seen_at=now,
                ),
                FinanceEvent(
                    provider="manual",
                    event_key="event-high",
                    calendar_type="earnings",
                    market="US",
                    event_date=date(2026, 6, 20),
                    title="High priority",
                    content="",
                    importance_score=9,
                    first_seen_at=now,
                    last_seen_at=now,
                ),
            ]
        )
        session.commit()

    items, total = MarketCalendarEventRepo(db=db).list_events_by_date_paginated(
        date(2026, 6, 20), page=1, limit=1
    )

    assert total == 2
    assert [item.title for item in items] == ["High priority"]
