"""Persist complete A-share sentiment sources and close observations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0056_market_sentiment"
down_revision = "0055_industry_history"
branch_labels = None
depends_on = None


def upgrade():
    json_type = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "market_sentiment_source_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("requested_trade_date", sa.Date()),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("quality", json_type, nullable=False),
        sa.UniqueConstraint("trade_date", "source_kind", name="uix_sentiment_source_date_kind"),
    )
    op.create_index(
        "ix_market_sentiment_source_snapshot_trade_date", "market_sentiment_source_snapshot", ["trade_date"]
    )
    op.create_table(
        "market_sentiment_snapshot",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", json_type, nullable=False),
    )


def downgrade():
    op.drop_table("market_sentiment_snapshot")
    op.drop_table("market_sentiment_source_snapshot")
