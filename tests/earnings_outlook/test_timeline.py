"""Filtering before cursor/limit shares precisely the card highlight predicate."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from sqlalchemy import event as sql_event

from tests.test_investment_timeline import TestDB, event
from finance_analysis.earnings_outlook.rules import digest, schedule
from finance_analysis.timeline.service import TimelineService
from finance_analysis.timeline.cursor import TimelineCursor
from finance_analysis.database.models.earnings_outlook import EarningsOutlookState


def test_high_confidence_filter_is_public_batched_and_cursor_safe(monkeypatch):
    now = datetime.now(timezone.utc)
    db = TestDB()
    member = NS(id=1, code="A.US", name="A", market="US", instrument_type="STOCK", listing_status="ACTIVE")
    service = TimelineService(db, resolver=NS(resolve_universe=lambda _: [member]))
    ids = []
    for i in range(5):
        e = event(
            db,
            event_key=f"earnings-{i}",
            calendar_type="earnings",
            market="US",
            symbol="A.US",
            event_datetime=now + timedelta(days=i + 1),
            event_date=(now + timedelta(days=i + 1)).date(),
            market_session="amc",
            reporting_period="2026-Q3",
        )
        # Existing helper returns ORM instance.
        ids.append(e.id)
        summary = dict(
            earnings_high=i != 0,
            reaction_high=False,
            expires_at=(now + timedelta(days=1)).isoformat(),
            release_cutoff=(now + timedelta(days=i + 1)).isoformat(),
        )
        if i == 1:
            summary["expires_at"] = (now - timedelta(hours=1)).isoformat()
        with db.get_session() as s, s.begin():
            s.add(
                EarningsOutlookState(
                    event_id=e.id,
                    status="success",
                    latest_prediction_id=i + 1,
                    schedule_hash=digest(schedule(e)),
                    summary=summary,
                )
            )
    statements = []
    sql_event.listen(
        db.engine, "before_cursor_execute", lambda c, cu, statement, p, co, ex: statements.append(statement)
    )
    first = service.list(timezone_name="America/New_York", high_confidence=True, limit=2)
    assert first["total"] == 3 and first["has_more"]
    second = service.list(
        timezone_name="America/New_York",
        high_confidence=True,
        limit=2,
        cursor=TimelineCursor.decode(first["next_cursor"]),
    )
    selected = [item.source_id for page in (first, second) for item in page["items"]]
    assert selected == list(reversed(ids[2:]))
    assert all(item.outlook["earnings_high"] for page in (first, second) for item in page["items"])
    # Per-page source and summary loads are batches; no per-card DB lookup.
    assert len(statements) <= 12
    plain = service.list(timezone_name="America/New_York", limit=20)
    assert plain["total"] == 5
