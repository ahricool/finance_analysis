"""Add finance events table.

Revision ID: 0004_add_finance_events
Revises: 0003_add_uid_user_scoping
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "0004_add_finance_events"
down_revision: Union[str, Sequence[str], None] = "0003_add_uid_user_scoping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "finance_events" in inspector.get_table_names():
        _create_indexes()
        return

    op.create_table(
        "finance_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("event_key", sa.String(length=96), nullable=False),
        sa.Column("calendar_type", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("counter_name", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column("activity_type", sa.String(length=64), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_type", sa.String(length=32), nullable=True),
        sa.Column("financial_market_time", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("star", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("data_kv_json", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_fingerprint", sa.String(length=96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uix_finance_events_event_key"),
    )
    _create_indexes()


def _create_indexes() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_provider ON finance_events (provider)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_finance_events_provider_event_id "
        "ON finance_events (provider_event_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_event_key ON finance_events (event_key)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_finance_events_calendar_type "
        "ON finance_events (calendar_type)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_market ON finance_events (market)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_symbol ON finance_events (symbol)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_event_date ON finance_events (event_date)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_finance_events_event_datetime "
        "ON finance_events (event_datetime)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_star ON finance_events (star)")


def downgrade() -> None:
    op.drop_index("ix_finance_events_star", table_name="finance_events")
    op.drop_index("ix_finance_events_event_datetime", table_name="finance_events")
    op.drop_index("ix_finance_events_event_date", table_name="finance_events")
    op.drop_index("ix_finance_events_symbol", table_name="finance_events")
    op.drop_index("ix_finance_events_market", table_name="finance_events")
    op.drop_index("ix_finance_events_calendar_type", table_name="finance_events")
    op.drop_index("ix_finance_events_event_key", table_name="finance_events")
    op.drop_index("ix_finance_events_provider_event_id", table_name="finance_events")
    op.drop_index("ix_finance_events_provider", table_name="finance_events")
    op.drop_table("finance_events")
