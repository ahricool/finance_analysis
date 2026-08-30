"""Add ETF Rotation V2 factors and market snapshots.

Revision ID: 0030_etf_rotation_v2
Revises: 0029_etf_rotation_stop_loss
Create Date: 2026-08-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_etf_rotation_v2"
down_revision: Union[str, Sequence[str], None] = "0029_etf_rotation_stop_loss"
branch_labels = None
depends_on = None

FLOAT_COLUMNS = (
    "weighted_slope_10d", "weighted_slope_25d", "annualized_slope_10d", "annualized_slope_25d",
    "trend_r2_25d", "trend_quality_25d", "efficiency_ratio_20d", "trend_acceleration",
    "rs_20d", "rs_60d", "risk_adjusted_momentum_60d", "max_drawdown_20d", "max_drawdown_60d",
    "momentum_strength_score", "trend_quality_score", "relative_strength_score", "acceleration_score",
    "efficiency_score", "risk_adjusted_score", "composite_score",
)


def upgrade() -> None:
    for name in FLOAT_COLUMNS:
        op.add_column("etf_momentum_snapshot", sa.Column(name, sa.Float(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("relative_strength_ready", sa.Boolean(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("rank", sa.Integer(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("absolute_trend_eligible", sa.Boolean(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("liquidity_eligible", sa.Boolean(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("action", sa.String(length=8), nullable=True))
    op.add_column(
        "etf_momentum_snapshot",
        sa.Column("diagnostics", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                  nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_etf_momentum_snapshot_market_date_composite", "etf_momentum_snapshot",
                    ["market", "trade_date", "composite_score"])
    op.create_table(
        "etf_market_rotation_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("regime", sa.String(length=16), nullable=False),
        sa.Column("breadth_above_ma20", sa.Float(), nullable=False),
        sa.Column("breadth_above_ma60", sa.Float(), nullable=False),
        sa.Column("breadth_ma20_above_ma60", sa.Float(), nullable=False),
        sa.Column("benchmark_code", sa.String(length=32), nullable=False),
        sa.Column("benchmark_close", sa.Float(), nullable=False),
        sa.Column("benchmark_ma20_ratio", sa.Float(), nullable=False),
        sa.Column("benchmark_ma60_ratio", sa.Float(), nullable=False),
        sa.Column("benchmark_trend", sa.String(length=16), nullable=False),
        sa.Column("benchmark_above_ma20", sa.Boolean(), nullable=False),
        sa.Column("benchmark_above_ma60", sa.Boolean(), nullable=False),
        sa.Column("benchmark_ma20_above_ma60", sa.Boolean(), nullable=False),
        sa.Column(
            "diagnostics",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_etf_market_rotation_market"),
        sa.CheckConstraint("regime IN ('RISK_ON', 'NEUTRAL', 'RISK_OFF')", name="ck_etf_market_rotation_regime"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "market", name="uix_etf_market_rotation_date_market"),
    )
    op.create_index("ix_etf_market_rotation_market_date", "etf_market_rotation_snapshot", ["market", "trade_date"])


def downgrade() -> None:
    op.drop_index("ix_etf_market_rotation_market_date", table_name="etf_market_rotation_snapshot")
    op.drop_table("etf_market_rotation_snapshot")
    op.drop_index("ix_etf_momentum_snapshot_market_date_composite", table_name="etf_momentum_snapshot")
    for name in ("diagnostics", "action", "liquidity_eligible", "absolute_trend_eligible", "rank",
                 "relative_strength_ready", *reversed(FLOAT_COLUMNS)):
        op.drop_column("etf_momentum_snapshot", name)
