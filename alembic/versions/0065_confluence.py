"""Persist confluence generations and compact scoring evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0065_confluence"
down_revision = "0064_dragon_tiger_flow"
branch_labels = None
depends_on = None


def upgrade():
    json_type = JSONB().with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "confluence_run",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("source_availability", json_type, nullable=False),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_confluence_run_market"),
    )
    op.create_table(
        "confluence_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confluence_score", sa.Float()),
        sa.Column("available_weight", sa.Integer(), nullable=False),
        sa.Column("available_signal_count", sa.Integer(), nullable=False),
        sa.Column("positive_signal_count", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("strong_confluence", sa.Boolean(), nullable=False),
        sa.Column("signals", json_type, nullable=False),
        sa.Column("reasons", json_type, nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market", "trade_date", "instrument_id", name="uix_confluence_market_date_instrument"),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_confluence_market"),
        sa.CheckConstraint(
            "confluence_score IS NULL OR confluence_score BETWEEN 0 AND 100", name="ck_confluence_score"
        ),
        sa.CheckConstraint(
            "positive_signal_count <= available_signal_count AND available_signal_count BETWEEN 0 AND 5",
            name="ck_confluence_counts",
        ),
    )


def downgrade():
    op.drop_table("confluence_snapshot")
    op.drop_table("confluence_run")
