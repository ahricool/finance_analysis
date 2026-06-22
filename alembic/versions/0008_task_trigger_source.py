"""Add task trigger source metadata.

Revision ID: 0008_task_trigger_source
Revises: 0007_task_dedupe_key
Create Date: 2026-06-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_task_trigger_source"
down_revision: Union[str, Sequence[str], None] = "0007_task_dedupe_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent against the collapsed baseline (0001), which already creates these
    # columns/indexes from the current ORM metadata.
    op.execute("ALTER TABLE task ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(32)")
    op.execute("ALTER TABLE task ADD COLUMN IF NOT EXISTS triggered_by_uid INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_trigger_source ON task (trigger_source)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_triggered_by_uid ON task (triggered_by_uid)")


def downgrade() -> None:
    op.drop_index("ix_task_triggered_by_uid", table_name="task")
    op.drop_index("ix_task_trigger_source", table_name="task")
    op.drop_column("task", "triggered_by_uid")
    op.drop_column("task", "trigger_source")
