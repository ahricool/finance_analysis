"""Add signal timing fields to Trend Following snapshots.

Revision ID: 0032_trend_following_signal
Revises: 0031_trend_following
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_trend_following_signal"
down_revision: Union[str, Sequence[str], None] = "0031_trend_following"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trend_following_snapshot", sa.Column("signal_date", sa.Date(), nullable=True))
    op.add_column("trend_following_snapshot", sa.Column("signal_price", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("trend_following_snapshot", "signal_price")
    op.drop_column("trend_following_snapshot", "signal_date")
