"""Real PostgreSQL checks for timezone behavior and deployed migration schema."""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, inspect

from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.news import NewsIntel, NewsIntelUsage
from finance_analysis.database.models.news_analysis import NewsAnalysis
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.session import DatabaseManager
from finance_analysis.timeline.cursor import TimelineCursor
from finance_analysis.timeline.service import TimelineService  # pragma: allowlist secret


def cleanup_entries(db, ids):
    db._run_write_transaction(
        "timeline-test.cleanup", lambda session: session.execute(delete(FinanceEvent).where(FinanceEvent.id.in_(ids)))
    )


def test_migrated_postgresql_schema_has_no_calendar_or_news_context():  # pragma: allowlist secret
    db = DatabaseManager.get_instance()
    inspector = inspect(db._engine)
    assert "calendar" not in inspector.get_table_names()
    for model in (TimelineEntry, NewsIntel, NewsIntelUsage, NewsAnalysis):
        actual = {column["name"] for column in inspector.get_columns(model.__tablename__)}
        assert actual == set(model.__table__.columns.keys())
    assert "uid" not in {column["name"] for column in inspector.get_columns("timeline_entries")}


def test_postgresql_day_boundaries_all_day_events_and_cutoff_agree():  # pragma: allowlist secret
    db = DatabaseManager.get_instance()
    key = "timeline-test-" + uuid4().hex
    repo = CalendarMarkerRepo(db)
    entry = repo.create(
        entry_type="us_premarket",
        market="US",
        event_time=datetime(2099, 9, 6, 1, tzinfo=timezone.utc),
        title="Timezone check",
        summary="Timezone",
        content="Test",
        importance="normal",
        actionability="none",
    )

    def seed(session):
        session.add(
            FinanceEvent(
                provider="test",
                event_key=key,
                calendar_type="macro",
                market="US",
                event_date=date(2099, 9, 6),
                title="FOMC",
                content="Decision",
            )
        )

    db._run_write_transaction("timeline-test.seed", seed)
    try:
        service = TimelineService(db)
        query = dict(timezone_name="Asia/Shanghai", end_date=date(2099, 9, 6))
        result = service.list(**query)
        titles = [item.title for item in result["items"]]
        assert titles[:2] == ["FOMC", "Timezone check"]
        event = next(item for item in result["items"] if item.category == "event")
        assert event.event_time == datetime(2099, 9, 6, 4, tzinfo=timezone.utc)
        assert event.detail_payload["all_day"] is True
        assert event.importance == "critical"
        assert event.calendar_type == "macro"
        # The all-day US event anchors at 04:00 UTC, which is still 2099-09-06 midnight in New York.
        eastern = service.list(timezone_name="America/New_York", end_date=date(2099, 9, 5))
        assert [item.title for item in eastern["items"][:1]] == ["Timezone check"]
    finally:
        cleanup_entries(db, [entry.id])
        db._run_write_transaction(
            "timeline-test.cleanup",
            lambda session: session.execute(delete(FinanceEvent).where(FinanceEvent.event_key == key)),
        )


def load_migration(name):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / f"alembic/versions/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_drops_calendar_and_moves_existing_news_usage(monkeypatch):
    from sqlalchemy import text

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db = DatabaseManager.get_instance()
    schema = "timeline_migration_" + uuid4().hex
    migration = load_migration("0043_investment_timeline")
    with db._engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    "CREATE TABLE news_intel (id SERIAL PRIMARY KEY, code VARCHAR(10), "
                    "title VARCHAR(300), url VARCHAR(1000), dimension VARCHAR(32), "
                    "query_id VARCHAR(64), uid INTEGER, fetched_at TIMESTAMPTZ)"
                )
            )
            connection.execute(text("CREATE TABLE calendar (id INTEGER PRIMARY KEY, content TEXT)"))
            connection.execute(
                text(
                    "INSERT INTO news_intel (code,title,url,dimension,query_id,uid) "
                    "VALUES ('NVDA','Fact','https://example.com/fact','premarket_news','q1',7)"
                )
            )
            connection.execute(text("INSERT INTO calendar VALUES (1, 'discarded task log')"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert "calendar" not in inspect(connection).get_table_names()
            assert "dimension" not in {column["name"] for column in inspect(connection).get_columns("news_intel")}
            assert connection.execute(text("SELECT title FROM news_intel")).scalar_one() == "Fact"
            assert connection.execute(text("SELECT usage_type,query_id,symbol,uid FROM news_intel_usage")).one() == (
                "premarket_news",
                "q1",
                "NVDA",
                7,
            )
            assert connection.execute(text("SELECT COUNT(*) FROM timeline_entries")).scalar_one() == 0
            migration.upgrade()  # Fresh bootstrap creates tables before the migration; creation is idempotent.
        finally:
            transaction.rollback()


def test_public_timeline_migration_drops_notes_and_owner_but_keeps_reports(monkeypatch):
    from sqlalchemy import text

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db = DatabaseManager.get_instance()
    schema = "public_timeline_" + uuid4().hex
    legacy = load_migration("0043_investment_timeline")
    migration = load_migration("0047_public_timeline")
    with db._engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("CREATE TABLE news_intel (id SERIAL PRIMARY KEY, fetched_at TIMESTAMPTZ)"))
            operations = Operations(MigrationContext.configure(connection))
            monkeypatch.setattr(legacy, "op", operations)
            monkeypatch.setattr(migration, "op", operations)
            legacy.upgrade()
            for entry_type in ("manual_note", "a_share_pre_close", "us_premarket", "us_postmarket"):
                connection.execute(
                    text(
                        "INSERT INTO timeline_entries "
                        "(uid, entry_type, event_time, title, summary, content, importance, actionability) "
                        "VALUES (7, :entry_type, CURRENT_TIMESTAMP, 't', 's', 'c', 'normal', 'none')"
                    ),
                    {"entry_type": entry_type},
                )
            migration.upgrade()
            columns = {column["name"] for column in inspect(connection).get_columns("timeline_entries")}
            assert "uid" not in columns
            kept = connection.execute(text("SELECT entry_type FROM timeline_entries ORDER BY entry_type")).scalars()
            assert list(kept) == ["a_share_pre_close", "us_postmarket", "us_premarket"]
            try:
                connection.execute(text("SAVEPOINT note_check"))
                connection.execute(
                    text(
                        "INSERT INTO timeline_entries "
                        "(entry_type, event_time, title, summary, content, importance, actionability) "
                        "VALUES ('manual_note', CURRENT_TIMESTAMP, 't', 's', 'c', 'normal', 'none')"
                    )
                )
                raise AssertionError("manual_note must violate the timeline check constraint")
            except Exception as exc:  # noqa: BLE001 - the constraint error type is driver specific
                assert "ck_timeline_type" in str(exc)
            connection.execute(text("ROLLBACK TO SAVEPOINT note_check"))
            migration.upgrade()  # Idempotent for databases bootstrapped from the current ORM metadata.
        finally:
            transaction.rollback()


def test_connection_keeps_utc_after_pool_rollback():
    from sqlalchemy import text

    db = DatabaseManager.get_instance()
    with db._engine.connect() as connection:
        assert connection.execute(text("SHOW timezone")).scalar_one() == "UTC"
        connection.rollback()
        assert connection.execute(text("SHOW timezone")).scalar_one() == "UTC"


def test_postgresql_news_freshness_and_feed_chronology(monkeypatch):
    from datetime import timedelta

    db = DatabaseManager.get_instance()
    now = datetime(2099, 9, 6, 8, tzinfo=timezone.utc)
    key = "news-time-" + uuid4().hex[:16]
    monkeypatch.setattr("finance_analysis.database.session.utc_now", lambda: now)

    def seed(session):
        for index, published in enumerate([now, None, now - timedelta(days=30)]):
            fact = NewsIntel(
                title=str(index), url=f"{key}/{index}", published_date=published, fetched_at=now - timedelta(days=8)
            )
            session.add(fact)
            session.flush()
            session.add(NewsIntelUsage(news_intel_id=fact.id, usage_type="premarket_news", symbol=key, observed_at=now))
            session.add(
                NewsAnalysis(
                    news_intel_id=fact.id,
                    analysis_type="premarket",
                    prompt_version="test",
                    analyzed_at=now + timedelta(hours=index),
                    importance="critical" if index == 0 else "normal",
                    importance_score=10 - index,
                    actionability="watch",
                )
            )

    db._run_write_transaction("test.seed", seed)
    try:
        assert {item.title for item in db.get_recent_news(key, days=1)} == {"0", "1"}
        query = dict(timezone_name="Asia/Shanghai", end_date=now.date(), category="news")
        service = TimelineService(db)
        items = [item for item in service.list(**query)["items"] if item.detail_payload["url"].startswith(key)]
        # Without a range floor the cutoff keeps older publications, still newest first.
        assert [item.title for item in items] == ["1", "0", "2"]
        assert [item.event_time for item in items[:2]] == [now + timedelta(hours=1), now]
    finally:
        db._run_write_transaction(
            "test.cleanup", lambda session: session.execute(delete(NewsIntel).where(NewsIntel.url.like(key + "/%")))
        )


def test_postgresql_cursor_survives_top_insert_and_deleted_anchor():
    from datetime import timedelta

    from sqlalchemy import event as sqlalchemy_event

    db = DatabaseManager.get_instance()
    now = datetime(2099, 9, 6, 8, 0, 0, 123456, tzinfo=timezone.utc)
    repo = CalendarMarkerRepo(db)
    ids = []
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sqlalchemy_event.listen(db._engine, "before_cursor_execute", capture)
    try:
        for title in "DCBA":
            row = repo.create(
                entry_type="us_premarket",
                market="US",
                event_time=now,
                title=title,
                summary="test",
                content="test",
                importance="normal",
                actionability="none",
            )
            ids.append(row.id)
        query = dict(timezone_name="Asia/Shanghai", end_date=now.date(), category="event", calendar_type="earnings", market="US")
        service = TimelineService(db)
        first = service.list(**query, limit=2)
        assert [item.title for item in first["items"]] == ["A", "B"]
        ids.append(
            repo.create(
                entry_type="us_premarket",
                market="US",
                event_time=now + timedelta(seconds=1),
                title="X",
                summary="test",
                content="test",
                importance="normal",
                actionability="none",
            ).id
        )
        cleanup_entries(db, [first["items"][-1].source_id])
        second = service.list(**query, cursor=TimelineCursor.decode(first["next_cursor"]), limit=2)
        assert [item.title for item in second["items"]] == ["C", "D"]
        assert all("OFFSET" not in statement.upper() for statement in statements)
    finally:
        sqlalchemy_event.remove(db._engine, "before_cursor_execute", capture)
        cleanup_entries(db, ids)


class CalendarMarkerRepo:
    def __init__(self, db):
        self.db = db

    def create(self, *, event_time, title, **kwargs):
        def write(session):
            row = FinanceEvent(provider="test", event_key=uuid4().hex, calendar_type="earnings", market="US",
                               symbol="TEST.US", event_date=event_time.date(), event_datetime=event_time,
                               title=title, content="Test")
            session.add(row)
            session.flush()
            return row
        return self.db._run_write_transaction("test.seed", write)
