"""Add persistent task execution records.

Revision ID: 0006_add_task_records
Revises: 0005_drop_portfolio_tables
Create Date: 2026-06-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "0006_add_task_records"
down_revision: Union[str, Sequence[str], None] = "0005_drop_portfolio_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task" not in inspector.get_table_names():
        op.create_table(
            "task",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("task_type", sa.String(length=64), nullable=False),
            sa.Column("task_name", sa.String(length=128), nullable=True),
            sa.Column("uid", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("message", sa.String(length=255), nullable=True),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("task_log", sa.String(length=255), nullable=True),
            sa.Column("parent_task_id", sa.String(length=64), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("scheduler_job_id", sa.String(length=96), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", name="uix_task_task_id"),
        )
    _create_indexes()


def _create_indexes() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_task_type ON task (task_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_uid ON task (uid)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_source ON task (source)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_status ON task (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_parent_task_id ON task (parent_task_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_scheduler_job_id ON task (scheduler_job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_created_at ON task (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_type_created_at ON task (task_type, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_status_created_at ON task (status, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_uid_created_at ON task (uid, created_at)")


def downgrade() -> None:
    op.drop_index("ix_task_uid_created_at", table_name="task")
    op.drop_index("ix_task_status_created_at", table_name="task")
    op.drop_index("ix_task_type_created_at", table_name="task")
    op.drop_index("ix_task_created_at", table_name="task")
    op.drop_index("ix_task_scheduler_job_id", table_name="task")
    op.drop_index("ix_task_parent_task_id", table_name="task")
    op.drop_index("ix_task_status", table_name="task")
    op.drop_index("ix_task_source", table_name="task")
    op.drop_index("ix_task_uid", table_name="task")
    op.drop_index("ix_task_task_type", table_name="task")
    op.drop_table("task")
