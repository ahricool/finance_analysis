"""Record versioned intraday evaluation evidence without rewriting historical snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0082_intraday_evaluation"
down_revision = "0081_quant_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intraday_confirmation_evaluation",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_intraday_evaluation_market"),
    )


def downgrade():
    op.drop_table("intraday_confirmation_evaluation")
