"""Frozen private CN/US pre-close holdings reviews."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0088_holdings_review"
down_revision = "0087_retire_trade_engine"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "holdings_review",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_snapshot", JSONB(), nullable=False),
        sa.Column("decision", JSONB(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("search_evidence", JSONB(), nullable=False),
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notification.id", ondelete="SET NULL")),
        sa.Column("error", sa.String(500)),
        sa.Column("model", sa.String(160)),
        sa.Column("backend", sa.String(32)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("uid", "market", "trade_date", name="uix_holdings_review_scope"),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_holdings_review_market"),
        sa.CheckConstraint("status IN ('processing','completed','failed')", name="ck_holdings_review_status"),
    )
    op.create_index("ix_holdings_review_uid_market_date", "holdings_review", ["uid", "market", "trade_date"])


def downgrade():
    op.drop_table("holdings_review")
