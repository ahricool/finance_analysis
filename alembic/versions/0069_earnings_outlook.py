"""Public earnings research, immutable predictions and independent review state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0069_earnings_outlook"
down_revision = "0068_us_postmarket_sync"
branch_labels = None
depends_on = None


def upgrade():
    jt = JSONB().with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "earnings_research",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("finance_events.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("bundle", jt, nullable=False),
        sa.Column("search_evidence", jt, nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("backend", sa.String(32)),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_earnings_research_event_id", "earnings_research", ["event_id"])
    op.create_index("ix_earnings_research_cache_key", "earnings_research", ["cache_key"])
    op.create_table(
        "earnings_prediction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("finance_events.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id"), nullable=False),
        sa.Column("research_id", sa.Integer(), sa.ForeignKey("earnings_research.id"), nullable=False),
        sa.Column("schedule_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("context", jt, nullable=False),
        sa.Column("prediction", jt, nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("backend", sa.String(32)),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_trading_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("event_id", "stage", "input_hash", name="uq_earnings_prediction_input"),
    )
    op.create_index("ix_earnings_prediction_event_id", "earnings_prediction", ["event_id"])
    op.create_table(
        "earnings_outlook_state",
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("finance_events.id"), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("latest_prediction_id", sa.Integer(), sa.ForeignKey("earnings_prediction.id")),
        sa.Column("summary", jt, nullable=False),
        sa.Column("schedule_hash", sa.String(64)),
        sa.Column("frozen_schedule_hash", sa.String(64)),
        sa.Column("actual", jt),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("earnings_outlook_state")
    op.drop_table("earnings_prediction")
    op.drop_table("earnings_research")
