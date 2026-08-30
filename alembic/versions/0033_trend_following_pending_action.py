"""Persist delayed Trend Following execution actions.

Revision ID: 0033_trend_pending_action
Revises: 0032_trend_following_signal
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_trend_pending_action"
down_revision: Union[str, Sequence[str], None] = "0032_trend_following_signal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trend_following_snapshot", sa.Column("pending_action", sa.String(length=24), nullable=True))
    op.add_column("trend_following_snapshot", sa.Column("pending_since", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("trend_following_snapshot", "pending_since")
    op.drop_column("trend_following_snapshot", "pending_action")
