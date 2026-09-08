"""Exercise old finance_events data through the real Alembic operations."""

import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from finance_analysis.database.models import FinanceEvent


def migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0045_calendar_sources.py"
    spec = importlib.util.spec_from_file_location("calendar_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def old_table(connection):
    columns = []
    for col in FinanceEvent.__table__.columns:
        if col.name in {"reporting_period", "eps_estimate", "reported_eps", "eps_surprise_pct"}:
            continue
        name = "financial_market_time" if col.name == "market_session" else col.name
        columns.append(sa.Column(name, col.type, primary_key=col.primary_key, nullable=col.nullable))
    columns.extend(
        [
            sa.Column("activity_type", sa.String(64)),
            sa.Column("date_type", sa.String(32)),
            sa.Column("star", sa.Integer),
            sa.Column("data_kv_json", sa.Text),
        ]
    )
    table = sa.Table(
        "finance_events", sa.MetaData(), *columns, sa.UniqueConstraint("event_key", name="uix_finance_events_event_key")
    )
    sa.Index("ix_finance_events_star", table.c.star)
    table.create(connection)
    return table


def exercise_migration(connection, monkeypatch):
    old = old_table(connection)
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    values = dict(
        provider="longbridge",
        provider_event_id="old-id",
        calendar_type="earnings",
        market="US",
        symbol="NVDA",
        counter_name="NVIDIA",
        event_type="Release",
        activity_type="Earnings",
        event_date=date(2026, 6, 20),
        financial_market_time="after_close",
        title="NVIDIA 财报",
        content="Q2 earnings\n- 重要性 star：3",
        star=3,
        currency="USD",
        raw_payload_json='{"id":"old-id"}',
        importance_score=9,
        first_seen_at=now,
        last_seen_at=now,
        notified_at=now,
        created_at=now,
        updated_at=now,
    )
    connection.execute(
        old.insert(),
        [
            {**values, "id": 1, "event_key": "old-stable-key"},
            {**values, "id": 2, "event_key": "old-duplicate-key"},
            {**values, "id": 3, "event_key": "old-dividend", "calendar_type": "dividend"},
            {**values, "id": 4, "event_key": "old-hk", "market": "HK"},
        ],
    )
    module = migration_module()
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    module.upgrade()
    new = sa.Table("finance_events", sa.MetaData(), autoload_with=connection)
    assert set(new.c.keys()) == set(FinanceEvent.__table__.c.keys())
    assert not any("star" in index["column_names"] for index in sa.inspect(connection).get_indexes("finance_events"))
    rows = list(connection.execute(sa.select(new)).mappings())
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == 1 and row["event_key"] == "old-stable-key" and row["symbol"] == "NVDA.US"
    assert row["market_session"] == "amc" and row["importance_score"] is None
    assert row["notified_at"] is not None and row["notification_fingerprint"]
    audit = json.loads(row["raw_payload_json"])
    assert audit["longbridge"]["legacy_metadata"]["star"] == 3
    assert "star" not in row["content"]
    with pytest.raises(RuntimeError, match="irreversible"):
        module.downgrade()


def test_migration_sqlite(monkeypatch):
    with sa.create_engine("sqlite://").begin() as connection:
        exercise_migration(connection, monkeypatch)


def test_migration_postgresql(monkeypatch):
    import os
    from uuid import uuid4

    url = os.getenv("CALENDAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CALENDAR_TEST_DATABASE_URL is an explicit isolated PostgreSQL test database")
    engine = sa.create_engine(url)
    schema = "calendar_test_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            exercise_migration(connection, monkeypatch)
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()
