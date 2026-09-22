"""Daily immutable Signal Center inputs, screening audit and final decision."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0067_signal_center"
down_revision = "0066_confluence_rules"
branch_labels = None
depends_on = None


def upgrade():
    jt = JSONB().with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "signal_center_run",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("signal_date", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("selected_symbol", sa.String(32)),
        sa.Column("decision", sa.String(16)),
        sa.Column("confidence", sa.String(8)),
        sa.Column("candidate_snapshot", jt, nullable=False),
        sa.Column("analysis", jt),
        sa.Column("model", sa.String(160)),
        sa.Column("backend", sa.String(16)),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("screening", jt),
        sa.Column("final_prompt", sa.Text()),
        sa.Column("raw_response", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_signal_center_market"),
        sa.CheckConstraint("status IN ('pending','completed','failed','skipped')", name="ck_signal_center_status"),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('low','medium','high')", name="ck_signal_center_confidence"
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND decision IS NOT NULL AND analysis IS NOT NULL AND confidence IS NOT NULL AND "
            "((decision = 'BUY' AND selected_symbol IS NOT NULL) OR "
            "(decision = 'NO_TRADE' AND selected_symbol IS NULL))) OR "
            "(status <> 'completed' AND decision IS NULL AND selected_symbol IS NULL)",
            name="ck_signal_center_decision",
        ),
    )


def downgrade():
    op.drop_table("signal_center_run")
