"""Add signal direction and version metadata.

Revision ID: 0013_signal_metadata
Revises: 0012_add_signal
Create Date: 2026-06-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0013_signal_metadata"
down_revision: Union[str, Sequence[str], None] = "0012_add_signal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("signal")}
    if "signal_version" not in columns:
        op.add_column(
            "signal",
            sa.Column("signal_version", sa.String(length=32), server_default="v1", nullable=False),
        )
    if "direction" not in columns:
        op.add_column(
            "signal",
            sa.Column("direction", sa.String(length=16), server_default="neutral", nullable=False),
        )

    constraints = {item["name"] for item in inspect(bind).get_check_constraints("signal")}
    if "ck_signal_direction" not in constraints:
        op.create_check_constraint(
            "ck_signal_direction",
            "signal",
            "direction IN ('bullish', 'bearish', 'sideways', 'neutral')",
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_signal_direction_signal_at "
        "ON signal (direction, signal_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_signal_type_signal_at "
        "ON signal (signal_type, signal_at)"
    )


def downgrade() -> None:
    op.drop_index("ix_signal_type_signal_at", table_name="signal")
    op.drop_index("ix_signal_direction_signal_at", table_name="signal")
    op.drop_constraint("ck_signal_direction", "signal", type_="check")
    op.drop_column("signal", "direction")
    op.drop_column("signal", "signal_version")
