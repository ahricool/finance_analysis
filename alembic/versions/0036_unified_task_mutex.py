"""Replace task-record dedupe locks with scheduled-slot idempotency.

Revision ID: 0036_unified_task_mutex
Revises: 0035_etf_fast_rotation
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_unified_task_mutex"
down_revision: Union[str, Sequence[str], None] = "0035_etf_fast_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "task" in inspector.get_table_names():
        task_indexes = {index["name"] for index in inspector.get_indexes("task")}
        for index_name in ("uix_task_active_dedupe", "ix_task_dedupe_status", "ix_task_dedupe_key"):
            if index_name in task_indexes:
                op.drop_index(index_name, table_name="task")
        if "dedupe_key" in {column["name"] for column in inspector.get_columns("task")}:
            with op.batch_alter_table("task") as batch_op:
                batch_op.drop_column("dedupe_key")

    if "scheduled_task_slot" not in inspector.get_table_names():
        op.create_table(
            "scheduled_task_slot",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("job_id", sa.String(length=96), nullable=False),
            sa.Column("trading_date", sa.Date(), nullable=False),
            sa.Column("scheduled_slot", sa.DateTime(timezone=True), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column(
                "completed_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "job_id",
                "trading_date",
                "scheduled_slot",
                name="uix_scheduled_task_slot_identity",
            ),
        )


def downgrade() -> None:
    op.drop_table("scheduled_task_slot")
    op.add_column("task", sa.Column("dedupe_key", sa.String(length=160), nullable=True))
    op.create_index("ix_task_dedupe_key", "task", ["dedupe_key"], unique=False)
    op.create_index("ix_task_dedupe_status", "task", ["dedupe_key", "status"], unique=False)
    op.create_index(
        "uix_task_active_dedupe",
        "task",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text(
            "dedupe_key IS NOT NULL AND status IN ('pending','processing','retrying')"
        ),
    )
