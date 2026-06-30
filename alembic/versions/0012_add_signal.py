"""Add persisted signals and incremental evaluation data.

Revision ID: 0012_add_signal
Revises: 0011_drop_backtest_tables
Create Date: 2026-06-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0012_add_signal"
down_revision: Union[str, Sequence[str], None] = "0011_drop_backtest_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "signal" in inspect(bind).get_table_names():
        _create_indexes()
        return

    op.create_table(
        "signal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=True),
        sa.Column("signal_type", sa.String(length=80), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US', 'HK')", name="ck_signal_market"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes()


def _create_indexes() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_signal_signal_at ON signal (signal_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_signal_market_signal_at_id "
        "ON signal (market, signal_at, id)"
    )


def downgrade() -> None:
    op.drop_index("ix_signal_market_signal_at_id", table_name="signal")
    op.drop_index("ix_signal_signal_at", table_name="signal")
    op.drop_table("signal")
