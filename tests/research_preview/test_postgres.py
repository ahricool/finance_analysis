"""Explicitly isolated PostgreSQL checks for atomic publication and JSONB storage."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.research_preview import ResearchPreview, ResearchPreviewItem
from finance_analysis.database.repositories.research_preview import PreviewRepository
from finance_analysis.trend_following import preview_cache as trend
from tests.research_preview.test_migration import migration
from tests.test_research_read_views import payload


@pytest.fixture
def postgres():
    url = os.getenv('PREVIEW_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Requires an explicitly isolated PREVIEW_TEST_POSTGRES_URL')
    engine = create_engine(url)
    schema = 'preview_test_' + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    for model in (Instrument, ResearchPreview, ResearchPreviewItem):
        model.__table__.create(scoped)

    class DB:
        def get_session(self):
            return Session(scoped)

        @contextmanager
        def session_scope(self):
            with Session(scoped) as session, session.begin():
                yield session

    try:
        yield PreviewRepository(DB()), scoped, schema
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_atomic_read_blocks_during_replace_and_old_worker_cannot_win(postgres):
    repo, engine, _ = postgres
    first = payload()
    trend.save_preview('CN', first, repository=repo)
    entered, release = Event(), Event()
    def pause(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith('DELETE FROM'):
            entered.set()
            assert release.wait(10)
    event.listen(engine, 'after_cursor_execute', pause)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            changed = {**first, 'preview_time': '2026-10-14T07:00:00Z', 'status': 'failed', 'snapshots': []}
            writer = pool.submit(trend.save_preview, 'CN', changed, repository=repo)
            assert entered.wait(5)
            reader = pool.submit(trend.load_preview, 'CN', repository=repo)
            older = pool.submit(trend.save_preview, 'CN', first, repository=repo)
            assert not reader.done()
            release.set()
            writer.result(timeout=10)
            older.result(timeout=10)
            result = reader.result(timeout=10)
            assert result['status'] == 'failed' and result['snapshots'] == []
    finally:
        release.set()
        event.remove(engine, 'after_cursor_execute', pause)
    assert trend.load_preview('CN', repository=repo)['status'] == 'failed'


def test_first_publications_and_incremental_updates_do_not_lose_rows(postgres):
    repo, _, _ = postgres
    stamp = datetime.now(timezone.utc)
    def publish(code):
        return repo.publish(
            'options_intelligence', 'US', 0, {'trade_date': stamp.date().isoformat()},
            [{'kind': 'stock', 'item_key': code, 'summary': {'symbol': code}}],
            observed_at=stamp, expires_at=stamp + timedelta(hours=1), merge=True,
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(publish, ('AAA.US', 'BBB.US')))
    loaded = repo.read('options_intelligence', 'US')
    assert {row['item_key'] for row in loaded['items']} == {'AAA.US', 'BBB.US'}


def test_jsonb_projection_and_migration_on_postgres(postgres):
    repo, engine, schema = postgres
    trend.save_preview('CN', payload(), repository=repo)
    assert trend.load_preview_view('CN', 'ranking', repository=repo)
    with engine.begin() as conn:
        assert str(inspect(conn).get_columns('research_preview_item', schema=schema)[-1]['type']) == 'JSONB'
        # Exercise the actual migration against a pre-existing Instrument table.
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        module = migration()
        module.op = Operations(MigrationContext.configure(conn))
        module.downgrade()
        module.upgrade()
        assert conn.execute(select(ResearchPreview)).all() == []
        assert conn.execute(select(ResearchPreviewItem)).all() == []
