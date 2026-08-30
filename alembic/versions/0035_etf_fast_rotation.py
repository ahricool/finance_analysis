"""Replace slow ETF rotation fields with 20-session fast-rotation fields.

Revision ID: 0035_etf_fast_rotation
Revises: 0034_trend_execution_context
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_etf_fast_rotation"
down_revision: Union[str, Sequence[str], None] = "0034_trend_execution_context"
branch_labels = None
depends_on = None

NEW_MOMENTUM_FLOAT_COLUMNS = (
    "ret_3d",
    "pct_rank_3d",
    "previous_3d_return",
    "momentum_acceleration_3d",
    "momentum_acceleration_5d",
    "ma10_ratio",
    "weighted_slope_5d",
    "weighted_slope_15d",
    "annualized_slope_5d",
    "annualized_slope_15d",
    "trend_r2_15d",
    "trend_quality_15d",
    "signed_efficiency_ratio_10d",
    "rs_5d",
    "rs_10d",
)
OLD_MOMENTUM_COLUMNS = (
    "ret_30d",
    "ret_60d",
    "rank_30d",
    "rank_60d",
    "pct_rank_30d",
    "pct_rank_60d",
    "momentum_acceleration",
    "ma60_ratio",
    "weighted_slope_25d",
    "annualized_slope_25d",
    "trend_r2_25d",
    "trend_quality_25d",
    "efficiency_ratio_20d",
    "rs_60d",
    "risk_adjusted_momentum_60d",
    "max_drawdown_60d",
    "risk_adjusted_score",
)
OLD_MARKET_COLUMNS = (
    "breadth_above_ma20",
    "breadth_above_ma60",
    "breadth_ma20_above_ma60",
    "benchmark_ma20_ratio",
    "benchmark_ma60_ratio",
    "benchmark_above_ma20",
    "benchmark_above_ma60",
    "benchmark_ma20_above_ma60",
)


def upgrade() -> None:
    op.drop_constraint("ck_etf_momentum_ranks_positive", "etf_momentum_snapshot", type_="check")
    op.drop_constraint("ck_etf_momentum_pct_ranks_range", "etf_momentum_snapshot", type_="check")
    for name in OLD_MOMENTUM_COLUMNS:
        op.drop_column("etf_momentum_snapshot", name)
    for name in NEW_MOMENTUM_FLOAT_COLUMNS:
        op.add_column("etf_momentum_snapshot", sa.Column(name, sa.Float(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("rank_3d", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_etf_momentum_ranks_positive",
        "etf_momentum_snapshot",
        "rank_1d > 0 AND (rank_3d IS NULL OR rank_3d > 0) "
        "AND rank_5d > 0 AND rank_10d > 0 AND rank_20d > 0",
    )
    op.create_check_constraint(
        "ck_etf_momentum_pct_ranks_range",
        "etf_momentum_snapshot",
        "pct_rank_1d BETWEEN 0 AND 100 "
        "AND (pct_rank_3d IS NULL OR pct_rank_3d BETWEEN 0 AND 100) "
        "AND pct_rank_5d BETWEEN 0 AND 100 "
        "AND pct_rank_10d BETWEEN 0 AND 100 AND pct_rank_20d BETWEEN 0 AND 100",
    )

    for name in OLD_MARKET_COLUMNS:
        op.drop_column("etf_market_rotation_snapshot", name)
    for name in (
        "positive_5d_breadth",
        "above_ma10_breadth",
        "benchmark_ret_5d",
        "benchmark_ma10_ratio",
        "benchmark_weighted_slope_10d",
    ):
        op.add_column("etf_market_rotation_snapshot", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    for name in (
        "positive_5d_breadth",
        "above_ma10_breadth",
        "benchmark_ret_5d",
        "benchmark_ma10_ratio",
        "benchmark_weighted_slope_10d",
    ):
        op.drop_column("etf_market_rotation_snapshot", name)
    for name in OLD_MARKET_COLUMNS:
        column_type = (
            sa.Boolean()
            if name in {"benchmark_above_ma20", "benchmark_above_ma60", "benchmark_ma20_above_ma60"}
            else sa.Float()
        )
        op.add_column("etf_market_rotation_snapshot", sa.Column(name, column_type, nullable=True))

    op.drop_constraint("ck_etf_momentum_ranks_positive", "etf_momentum_snapshot", type_="check")
    op.drop_constraint("ck_etf_momentum_pct_ranks_range", "etf_momentum_snapshot", type_="check")
    op.drop_column("etf_momentum_snapshot", "rank_3d")
    for name in reversed(NEW_MOMENTUM_FLOAT_COLUMNS):
        op.drop_column("etf_momentum_snapshot", name)
    for name in OLD_MOMENTUM_COLUMNS:
        column_type = sa.Integer() if name.startswith("rank_") else sa.Float()
        op.add_column("etf_momentum_snapshot", sa.Column(name, column_type, nullable=True))
    op.create_check_constraint(
        "ck_etf_momentum_ranks_positive",
        "etf_momentum_snapshot",
        "rank_1d > 0 AND rank_5d > 0 AND rank_10d > 0 AND rank_20d > 0 "
        "AND (rank_30d IS NULL OR rank_30d > 0) AND (rank_60d IS NULL OR rank_60d > 0)",
    )
    op.create_check_constraint(
        "ck_etf_momentum_pct_ranks_range",
        "etf_momentum_snapshot",
        "pct_rank_1d BETWEEN 0 AND 100 AND pct_rank_5d BETWEEN 0 AND 100 "
        "AND pct_rank_10d BETWEEN 0 AND 100 AND pct_rank_20d BETWEEN 0 AND 100",
    )
