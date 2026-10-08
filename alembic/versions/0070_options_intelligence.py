"""Source-preserving options snapshots, independent metrics, events and explanations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0070_options_intelligence"
down_revision = "0069_earnings_outlook"
branch_labels = None
depends_on = None


def upgrade():
    jt = JSONB().with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "option_contract",
        sa.Column("symbol", sa.String(64), primary_key=True),
        sa.Column("underlying_symbol", sa.String(32), nullable=False),
        sa.Column("option_type", sa.String(4), nullable=False),
        sa.Column("expiration", sa.Date(), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("multiplier", sa.Float()),
        sa.CheckConstraint("option_type IN ('call','put')", name="ck_option_contract_type"),
    )
    op.create_index("ix_option_contract_underlying_symbol", "option_contract", ["underlying_symbol"])
    op.create_table(
        "option_quote_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", jt, nullable=False),
        sa.Column("metrics", jt, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("symbol", "bucket", "mode", name="uq_option_snapshot_bucket"),
    )
    op.create_index("ix_option_snapshot_symbol_date", "option_quote_snapshot", ["symbol", "trade_date"])
    op.create_table(
        "option_daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("option_quote_snapshot.id"), nullable=False),
        sa.Column("metrics", jt, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "trade_date", name="uq_option_daily_symbol_date"),
    )
    op.create_table(
        "option_anomaly_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("contract_symbol", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("data_source", sa.String(16), nullable=False),
        sa.Column("feed_type", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_evidence", jt, nullable=False),
        sa.Column("latest_evidence", jt, nullable=False),
        sa.Column("changes", jt, nullable=False),
        sa.Column("validation", jt, nullable=False),
        sa.UniqueConstraint(
            "symbol",
            "contract_symbol",
            "event_type",
            "trade_date",
            "data_source",
            "feed_type",
            name="uq_option_event_daily",
        ),
    )
    op.create_index("ix_option_event_symbol_date", "option_anomaly_event", ["symbol", "trade_date"])
    op.create_table(
        "option_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("option_quote_snapshot.id"), nullable=False, unique=True),
        sa.Column("explanation", jt, nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for name in (
        "option_analysis",
        "option_anomaly_event",
        "option_daily_metrics",
        "option_quote_snapshot",
        "option_contract",
    ):
        op.drop_table(name)
