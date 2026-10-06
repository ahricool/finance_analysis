"""Exercise the existing PostgreSQL varchar schema, upgrade and rollback safety."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from finance_analysis.database.models.news import NewsIntel


def test_news_title_orm_retains_original_text():
    assert isinstance(NewsIntel.__table__.c.title.type, sa.Text)
    assert not NewsIntel.__table__.c.title.nullable


def test_existing_news_title_upgrade_postgresql(monkeypatch):
    url = os.getenv("NEWS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NEWS_TEST_DATABASE_URL must point to an isolated test database")
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0070_news_title_text.py"
    spec = importlib.util.spec_from_file_location("news_title_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(url)
    schema = "news_title_test_" + uuid4().hex
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(sa.text("CREATE TABLE news_intel (id INTEGER PRIMARY KEY, title VARCHAR(300) NOT NULL)"))
            conn.execute(sa.text("INSERT INTO news_intel VALUES (1, 'existing title')"))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
            module.upgrade()
            title = "汉" * 347
            conn.execute(sa.text("INSERT INTO news_intel VALUES (2, :title)"), {"title": title})
            assert conn.scalar(sa.text("SELECT title FROM news_intel WHERE id=2")) == title
            assert conn.scalar(sa.text("SELECT title FROM news_intel WHERE id=1")) == "existing title"
            savepoint = conn.begin_nested()
            try:
                with pytest.raises(sa.exc.DBAPIError):
                    module.downgrade()
            finally:
                savepoint.rollback()
            assert conn.scalar(sa.text("SELECT title FROM news_intel WHERE id=2")) == title
            conn.execute(sa.text("DELETE FROM news_intel WHERE id=2"))
            module.downgrade()
            assert conn.scalar(sa.text("SELECT title FROM news_intel WHERE id=1")) == "existing title"
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()
