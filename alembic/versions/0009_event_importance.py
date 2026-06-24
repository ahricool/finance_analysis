"""Add finance event importance assessment fields.

Revision ID: 0009_event_importance
Revises: 0008_task_trigger_source
Create Date: 2026-06-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_event_importance"
down_revision: Union[str, Sequence[str], None] = "0008_task_trigger_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_score INTEGER")
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_reason TEXT")
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_confidence FLOAT")
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_model VARCHAR(128)")
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_prompt_version VARCHAR(32)")
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_input_hash VARCHAR(64)")
    op.execute("ALTER TABLE finance_events ADD COLUMN IF NOT EXISTS importance_scored_at TIMESTAMP WITH TIME ZONE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_finance_events_importance_score ON finance_events (importance_score)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_finance_events_importance_input_hash "
        "ON finance_events (importance_input_hash)"
    )


def downgrade() -> None:
    op.drop_index("ix_finance_events_importance_input_hash", table_name="finance_events")
    op.drop_index("ix_finance_events_importance_score", table_name="finance_events")
    op.drop_column("finance_events", "importance_scored_at")
    op.drop_column("finance_events", "importance_input_hash")
    op.drop_column("finance_events", "importance_prompt_version")
    op.drop_column("finance_events", "importance_model")
    op.drop_column("finance_events", "importance_confidence")
    op.drop_column("finance_events", "importance_reason")
    op.drop_column("finance_events", "importance_score")
