"""Add nullable trend_duration_days to ETF Rotation and Trend Following snapshots.

Revision ID: 0048_trend_duration_days
Revises: 0047_public_timeline
Create Date: 2026-09-10

Historical rows stay NULL so old snapshots are distinguishable from a computed 0,
which means the as-of session failed the existing absolute-trend checks.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_trend_duration_days"
down_revision: Union[str, Sequence[str], None] = "0047_public_timeline"
branch_labels = None
depends_on = None

TABLES = (
    (
        "etf_momentum_snapshot",
        "ck_etf_trend_duration_days_non_negative",
    ),
    (
        "trend_following_snapshot",
        "ck_trend_following_trend_duration_days_non_negative",
    ),
)


def upgrade() -> None:
    for table, constraint in TABLES:
        op.add_column(table, sa.Column("trend_duration_days", sa.Integer(), nullable=True))
        condition = "trend_duration_days IS NULL OR trend_duration_days >= 0"
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.create_check_constraint(constraint, condition)
        else:
            op.create_check_constraint(constraint, table, condition)


def downgrade() -> None:
    for table, constraint in reversed(TABLES):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(constraint, type_="check")
                batch_op.drop_column("trend_duration_days")
        else:
            op.drop_constraint(constraint, table, type_="check")
            op.drop_column(table, "trend_duration_days")
