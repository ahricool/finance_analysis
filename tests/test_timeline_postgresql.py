"""Real PostgreSQL checks for timezone behavior and deployed migration schema."""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, inspect

from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.news import NewsIntel, NewsIntelUsage
from finance_analysis.database.models.news_analysis import NewsAnalysis
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.repositories.timeline import TimelineEntryRepo
from finance_analysis.database.session import DatabaseManager
from finance_analysis.timeline.service import TimelineService


def test_migrated_postgres_schema_has_no_calendar_or_news_context():
    db = DatabaseManager.get_instance()
    inspector = inspect(db._engine)
    assert "calendar" not in inspector.get_table_names()
    for model in (TimelineEntry, NewsIntel, NewsIntelUsage, NewsAnalysis):
        actual = {column["name"] for column in inspector.get_columns(model.__tablename__)}
        assert actual == set(model.__table__.columns.keys())


def test_postgresql_day_boundaries_all_day_events_and_summary_agree():
    db = DatabaseManager.get_instance()
    uid = 987654321
    key = "timeline-test-" + uuid4().hex
    repo = TimelineEntryRepo(db)
    entry = repo.create(
        uid=uid,
        entry_type="manual_note",
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
        query = dict(uid=uid, start_date=date(2099, 9, 6), end_date=date(2099, 9, 6), timezone_name="Asia/Shanghai")
        result = service.list(**query)
        assert result["total"] == 2
        event = next(item for item in result["items"] if item.category == "event")
        assert event.event_time == datetime(2099, 9, 6, 4, tzinfo=timezone.utc)
        assert event.detail_payload["all_day"] is True
        assert event.importance == "critical"
        assert service.summary(**query)[0].total == 2
        eastern = query | dict(timezone_name="America/New_York")
        assert service.list(**eastern)["total"] == 1
        assert service.summary(**eastern)[0].total == 1
        yesterday = eastern | dict(start_date=date(2099, 9, 5), end_date=date(2099, 9, 5))
        assert service.list(**yesterday)["items"][0].source_id == entry.id
    finally:
        repo.delete_note(entry.id, uid=uid)
        db._run_write_transaction(
            "timeline-test.cleanup",
            lambda session: session.execute(delete(FinanceEvent).where(FinanceEvent.event_key == key)),
        )


def test_migration_drops_calendar_and_moves_existing_news_usage(monkeypatch):
    import importlib.util
    from pathlib import Path

    from sqlalchemy import text

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db = DatabaseManager.get_instance()
    schema = "timeline_migration_" + uuid4().hex
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0043_investment_timeline.py"
    spec = importlib.util.spec_from_file_location("timeline_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
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


def test_connection_keeps_utc_after_pool_rollback():
    from sqlalchemy import text
    db = DatabaseManager.get_instance()
    with db._engine.connect() as connection:
        assert connection.execute(text("SHOW timezone")).scalar_one() == "UTC"
        connection.rollback()
        assert connection.execute(text("SHOW timezone")).scalar_one() == "UTC"
