"""Persist point-in-time context for pending Trend Following executions.

Revision ID: 0034_trend_execution_context
Revises: 0033_trend_pending_action
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_trend_execution_context"
down_revision: Union[str, Sequence[str], None] = "0033_trend_pending_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trend_following_snapshot", sa.Column("pending_regime", sa.String(length=16), nullable=True))
    op.add_column("trend_following_snapshot", sa.Column("pending_max_exposure", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("trend_following_snapshot", "pending_max_exposure")
    op.drop_column("trend_following_snapshot", "pending_regime")
