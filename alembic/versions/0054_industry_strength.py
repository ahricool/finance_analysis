"""Persist A-share industry observations separately from trading strategy snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0054_industry_strength"
down_revision = "0053_trend_states"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "industry_strength_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("industry_code", sa.String(32), nullable=False),
        sa.Column("industry_name", sa.String(128), nullable=False),
        sa.Column("close", sa.Float()),
        sa.Column("ret_1d", sa.Float()),
        sa.Column("ret_5d", sa.Float()),
        sa.Column("ret_10d", sa.Float()),
        sa.Column("ret_20d", sa.Float()),
        sa.Column("rs_5d", sa.Float()),
        sa.Column("rs_10d", sa.Float()),
        sa.Column("rs_20d", sa.Float()),
        sa.Column("rs_5d_percentile", sa.Float()),
        sa.Column("rs_10d_percentile", sa.Float()),
        sa.Column("rs_20d_percentile", sa.Float()),
        sa.Column("strength_score", sa.Float()),
        sa.Column("previous_5d_return", sa.Float()),
        sa.Column("momentum_acceleration_5d", sa.Float()),
        sa.Column("acceleration_percentile", sa.Float()),
        sa.Column("turnover_ratio_5d", sa.Float()),
        sa.Column("up_ratio", sa.Float()),
        sa.Column("above_ma5_ratio", sa.Float()),
        sa.Column("above_ma20_ratio", sa.Float()),
        sa.Column("equal_weight_return", sa.Float()),
        sa.Column("rs_5d_rank", sa.Integer()),
        sa.Column("rs_10d_rank", sa.Integer()),
        sa.Column("rs_20d_rank", sa.Integer()),
        sa.Column("strength_rank", sa.Integer()),
        sa.Column("rank_change_1d", sa.Integer()),
        sa.Column("rank_change_3d", sa.Integer()),
        sa.Column("rank_change_5d", sa.Integer()),
        sa.Column("constituent_count", sa.Integer()),
        sa.Column("valid_constituent_count", sa.Integer()),
        sa.Column("up_count", sa.Integer()),
        sa.Column("down_count", sa.Integer()),
        sa.Column("flat_count", sa.Integer()),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("data_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("members_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trade_date", "industry_code", name="uix_industry_strength_date_code"),
        sa.CheckConstraint(
            "state IN ('EMERGING','STRONG','NEUTRAL','COOLING','WEAK')", name="ck_industry_strength_state"
        ),
    )
    op.create_index("ix_industry_strength_snapshot_trade_date", "industry_strength_snapshot", ["trade_date"])
    op.create_index("ix_industry_strength_snapshot_industry_code", "industry_strength_snapshot", ["industry_code"])


def downgrade():
    op.drop_table("industry_strength_snapshot")
