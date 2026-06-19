"""Add task dedupe key for database-backed in-flight uniqueness.

Revision ID: 0007_task_dedupe_key
Revises: 0006_add_task_records
Create Date: 2026-06-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_task_dedupe_key"
down_revision: Union[str, Sequence[str], None] = "0006_add_task_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task", sa.Column("dedupe_key", sa.String(length=160), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_dedupe_key ON task (dedupe_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_task_dedupe_status ON task (dedupe_key, status)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uix_task_active_dedupe
        ON task (dedupe_key)
        WHERE dedupe_key IS NOT NULL
          AND status IN ('pending', 'processing', 'retrying')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_task_active_dedupe")
    op.drop_index("ix_task_dedupe_status", table_name="task")
    op.drop_index("ix_task_dedupe_key", table_name="task")
    op.drop_column("task", "dedupe_key")
