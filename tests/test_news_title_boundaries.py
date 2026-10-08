"""Bound raw news titles without a schema change or altered news identity."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import sessionmaker

from finance_analysis.database.models.news import NewsIntel, NewsIntelUsage
from finance_analysis.database.news import NewsItem
from finance_analysis.database.session import DatabaseManager


@pytest.fixture(params=["sqlite", "postgresql"])
def news_store(request):
    """Exercise the real writer; PostgreSQL must be an explicitly isolated test DB."""
    schema = None
    admin = None
    if request.param == "postgresql":
        url = os.getenv("NEWS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("NEWS_TEST_DATABASE_URL must point to an isolated test database")
        schema = "news_boundary_" + uuid4().hex
        admin = sa.create_engine(url)
        with admin.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = sa.create_engine("sqlite://")
    try:
        NewsIntel.__table__.create(engine)
        NewsIntelUsage.__table__.create(engine)
        db = object.__new__(DatabaseManager)
        db._engine = engine
        db._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        db._initialized = True
        yield db
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as conn:
                conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def news_item(**values):
    return NewsItem(**{"snippet": "", "source": "example", **values})


def save(db, items, *, code="MSFT.US", query_id="first"):
    return db.save_news_intel(code, "premarket_news", items, "longbridge", {"query_id": query_id})


def test_news_title_uses_existing_varchar_and_single_options_head():
    column = NewsIntel.__table__.c.title
    assert isinstance(column.type, sa.String) and not isinstance(column.type, sa.Text)
    assert column.type.length == 300 and not column.nullable
    assert ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == ["0070_options_intelligence"]


@pytest.mark.parametrize("title", ["a" * 299, "汉" * 300, "🙂" * 301, "汉🙂" * 180],
                         ids=["299-ascii", "300-chinese", "301-emoji", "360-mixed"])
def test_character_boundaries_preserve_batch_and_input(news_store, title):
    item = news_item(title="  " + title + "  ", snippet="正文" * 400, url="https://news.example/long")
    assert save(news_store, [item, news_item(title="short", url="https://news.example/short")]) == 2
    with news_store.get_session() as session:
        rows = session.scalars(sa.select(NewsIntel).order_by(NewsIntel.id)).all()
        assert [row.title for row in rows] == [title[:300], "short"]
        assert rows[0].snippet == item.snippet
        assert session.scalar(sa.select(sa.func.count()).select_from(NewsIntelUsage)) == 2
    assert item.title == "  " + title + "  "


def test_repeated_url_preserves_first_fact_and_usage_idempotency(news_store):
    original = news_item(title="汉" * 301, url="https://news.example/same")
    changed = news_item(title="🙂" * 301, url=original.url)
    assert save(news_store, [original]) == 1
    assert save(news_store, [changed]) == 0
    assert save(news_store, [changed], code="AAPL.US", query_id="second") == 0
    with news_store.get_session() as session:
        row = session.scalars(sa.select(NewsIntel)).one()
        assert row.title == original.title[:300]
        assert session.scalar(sa.select(sa.func.count()).select_from(NewsIntelUsage)) == 2


def test_url_less_hash_uses_full_title_before_truncation(news_store):
    prefix = "汉🙂" * 150
    items = [news_item(title=prefix + suffix, url="", source="same", published_date="2026-10-08")
             for suffix in ("甲", "乙")]
    assert save(news_store, items) == 2
    assert save(news_store, items) == 0
    with news_store.get_session() as session:
        rows = session.scalars(sa.select(NewsIntel)).all()
        assert [row.title for row in rows] == [prefix, prefix]
        expected = {news_store._build_fallback_url_key(
            item.title, item.source, news_store._parse_published_date(item.published_date)) for item in items}
        assert {row.url for row in rows} == expected
        assert len(expected) == 2


def test_postgresql_legacy_column_rejects_unbounded_title_but_writer_succeeds(news_store):
    if news_store._engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL enforces VARCHAR length; SQLite does not")
    column = next(col for col in sa.inspect(news_store._engine).get_columns("news_intel") if col["name"] == "title")
    assert column["type"].length == 300
    with pytest.raises(sa.exc.DataError):
        with news_store._engine.begin() as conn:
            conn.execute(sa.insert(NewsIntel).values(title="🙂" * 301, url="https://news.example/raw"))
    assert save(news_store, [news_item(title="🙂" * 301, url="https://news.example/safe")]) == 1
