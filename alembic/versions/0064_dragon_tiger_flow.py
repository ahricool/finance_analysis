"""Atomic daily Dragon Tiger source generations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0064_dragon_tiger_flow"
down_revision = "0063_portfolio_mutation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dragon_tiger_flow_batch",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("batch_id", sa.String(36), nullable=False, unique=True),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
    )


def downgrade():
    op.drop_table("dragon_tiger_flow_batch")
