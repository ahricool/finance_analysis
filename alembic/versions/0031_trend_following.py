"""Add independent Trend Following snapshots.

Revision ID: 0031_trend_following
Revises: 0030_etf_rotation_v2
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_trend_following"
down_revision: Union[str, Sequence[str], None] = "0030_etf_rotation_v2"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "trend_following_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("universe_key", sa.String(length=64), nullable=False),
        sa.Column("benchmark_code", sa.String(length=32), nullable=False),
        sa.Column("market_regime", sa.String(length=16), nullable=False),
        sa.Column("market_score", sa.Float(), nullable=False),
        sa.Column("suggested_max_exposure", sa.Float(), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("data_ready_count", sa.Integer(), nullable=False),
        sa.Column("data_coverage", sa.Float(), nullable=False),
        sa.Column("rankable_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("add_count", sa.Integer(), nullable=False),
        sa.Column("hold_count", sa.Integer(), nullable=False),
        sa.Column("reduce_count", sa.Integer(), nullable=False),
        sa.Column("exit_count", sa.Integer(), nullable=False),
        sa.Column("warnings", JSON_TYPE, nullable=False),
        sa.Column("features", JSON_TYPE, nullable=False),
        sa.Column("score_breakdown", JSON_TYPE, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_trend_following_summary_market"),
        sa.CheckConstraint("market_regime IN ('RISK_ON', 'NEUTRAL', 'RISK_OFF')", name="ck_trend_summary_regime"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market", "trade_date", name="uix_trend_following_summary_market_date"),
    )
    op.create_index("ix_trend_following_summary_market_date", "trend_following_summary", ["market", "trade_date"])
    op.create_table(
        "trend_following_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("universe_key", sa.String(length=64), nullable=False),
        sa.Column("market_regime", sa.String(length=16), nullable=False),
        sa.Column("market_score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("trend_score", sa.Float(), nullable=False),
        sa.Column("rs_score", sa.Float(), nullable=False),
        sa.Column("breakout_score", sa.Float(), nullable=False),
        sa.Column("alpha_score", sa.Float(), nullable=False),
        sa.Column("features", JSON_TYPE, nullable=False),
        sa.Column("score_breakdown", JSON_TYPE, nullable=False),
        sa.Column("setup", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=False),
        sa.Column("atr", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("last_add_price", sa.Float(), nullable=True),
        sa.Column("highest_close", sa.Float(), nullable=True),
        sa.Column("initial_stop", sa.Float(), nullable=True),
        sa.Column("trailing_stop", sa.Float(), nullable=True),
        sa.Column("next_add_price", sa.Float(), nullable=True),
        sa.Column("exit_level", sa.Float(), nullable=True),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.Date(), nullable=True),
        sa.Column("suggested_initial_weight", sa.Float(), nullable=True),
        sa.Column("suggested_max_weight", sa.Float(), nullable=True),
        sa.Column("reasons", JSON_TYPE, nullable=False),
        sa.Column("intraday_confirmation", sa.String(length=16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_trend_following_market"),
        sa.CheckConstraint("market_regime IN ('RISK_ON', 'NEUTRAL', 'RISK_OFF')", name="ck_trend_following_regime"),
        sa.CheckConstraint("market_score BETWEEN 0 AND 100", name="ck_trend_following_market_score"),
        sa.CheckConstraint("trend_score BETWEEN 0 AND 100", name="ck_trend_following_trend_score"),
        sa.CheckConstraint("rs_score BETWEEN 0 AND 100", name="ck_trend_following_rs_score"),
        sa.CheckConstraint("breakout_score BETWEEN 0 AND 100", name="ck_trend_following_breakout_score"),
        sa.CheckConstraint("alpha_score BETWEEN 0 AND 100", name="ck_trend_following_alpha_score"),
        sa.CheckConstraint("units BETWEEN 0 AND 4", name="ck_trend_following_units"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market", "trade_date", "code", name="uix_trend_following_market_date_code"),
    )
    op.create_index(
        "ix_trend_following_market_date_alpha",
        "trend_following_snapshot",
        ["market", "trade_date", "alpha_score"],
    )
    op.create_index("ix_trend_following_symbol_date", "trend_following_snapshot", ["symbol_id", "trade_date"])
    op.create_index(
        "ix_trend_following_market_date_state",
        "trend_following_snapshot",
        ["market", "trade_date", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_trend_following_market_date_state", table_name="trend_following_snapshot")
    op.drop_index("ix_trend_following_symbol_date", table_name="trend_following_snapshot")
    op.drop_index("ix_trend_following_market_date_alpha", table_name="trend_following_snapshot")
    op.drop_table("trend_following_snapshot")
    op.drop_index("ix_trend_following_summary_market_date", table_name="trend_following_summary")
    op.drop_table("trend_following_summary")
