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
    op.add_column("task", sa.Column("trigger_source", sa.String(length=32), nullable=True))
    op.add_column("task", sa.Column("triggered_by_uid", sa.Integer(), nullable=True))
    op.create_index("ix_task_trigger_source", "task", ["trigger_source"])
    op.create_index("ix_task_triggered_by_uid", "task", ["triggered_by_uid"])


def downgrade() -> None:
    op.drop_index("ix_task_triggered_by_uid", table_name="task")
    op.drop_index("ix_task_trigger_source", table_name="task")
    op.drop_column("task", "triggered_by_uid")
    op.drop_column("task", "trigger_source")
