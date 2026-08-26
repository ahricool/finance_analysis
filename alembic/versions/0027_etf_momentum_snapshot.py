"""Add ETF momentum rotation snapshots.

Revision ID: 0027_etf_momentum_snapshot
Revises: 0026_remove_source_priority
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_etf_momentum_snapshot"
down_revision: Union[str, Sequence[str], None] = "0026_remove_source_priority"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etf_momentum_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        *[sa.Column(f"ret_{window}d", sa.Float(), nullable=False) for window in (1, 5, 10, 20, 30, 60)],
        *[sa.Column(f"rank_{window}d", sa.Integer(), nullable=False) for window in (1, 5, 10, 20, 30, 60)],
        *[sa.Column(f"pct_rank_{window}d", sa.Float(), nullable=False) for window in (1, 5, 10, 20, 30, 60)],
        sa.Column("previous_5d_return", sa.Float(), nullable=False),
        sa.Column("momentum_acceleration", sa.Float(), nullable=False),
        sa.Column("rank_change_1d", sa.Integer()),
        sa.Column("rank_change_3d", sa.Integer()),
        sa.Column("rank_change_5d", sa.Integer()),
        sa.Column("ma20_ratio", sa.Float(), nullable=False),
        sa.Column("ma60_ratio", sa.Float(), nullable=False),
        sa.Column("volume_ratio_5d", sa.Float()),
        sa.Column("avg_amount_20d", sa.Float()),
        sa.Column("realized_vol_20d", sa.Float(), nullable=False),
        sa.Column("distance_from_20d_high", sa.Float(), nullable=False),
        sa.Column("momentum_score", sa.Float(), nullable=False),
        sa.Column("entry_score", sa.Float(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("overheated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("candidate_rank", sa.Integer()),
        sa.Column("is_candidate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "score_components",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("momentum_score BETWEEN 0 AND 100", name="ck_etf_momentum_score_range"),
        sa.CheckConstraint("entry_score BETWEEN 0 AND 100", name="ck_etf_entry_score_range"),
        sa.CheckConstraint(
            "rank_1d > 0 AND rank_5d > 0 AND rank_10d > 0 AND rank_20d > 0 AND rank_30d > 0 AND rank_60d > 0",
            name="ck_etf_momentum_ranks_positive",
        ),
        sa.CheckConstraint(
            "pct_rank_1d BETWEEN 0 AND 100 AND pct_rank_5d BETWEEN 0 AND 100 "
            "AND pct_rank_10d BETWEEN 0 AND 100 AND pct_rank_20d BETWEEN 0 AND 100 "
            "AND pct_rank_30d BETWEEN 0 AND 100 AND pct_rank_60d BETWEEN 0 AND 100",
            name="ck_etf_momentum_pct_ranks_range",
        ),
        sa.CheckConstraint(
            "state IN ('EMERGING','TRENDING','STRONG','COOLING','EXHAUSTED','WEAK','NEUTRAL')",
            name="ck_etf_momentum_state",
        ),
        sa.CheckConstraint("candidate_rank IS NULL OR candidate_rank > 0", name="ck_etf_candidate_rank_positive"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "symbol_id", name="uix_etf_momentum_snapshot_date_symbol"),
    )
    op.create_index("ix_etf_momentum_snapshot_date_entry", "etf_momentum_snapshot", ["trade_date", "entry_score"])
    op.create_index("ix_etf_momentum_snapshot_symbol_date", "etf_momentum_snapshot", ["symbol_id", "trade_date"])
    op.create_index(
        "ix_etf_momentum_snapshot_date_candidate",
        "etf_momentum_snapshot",
        ["trade_date", "is_candidate", "candidate_rank"],
    )


def downgrade() -> None:
    op.drop_index("ix_etf_momentum_snapshot_date_candidate", table_name="etf_momentum_snapshot")
    op.drop_index("ix_etf_momentum_snapshot_symbol_date", table_name="etf_momentum_snapshot")
    op.drop_index("ix_etf_momentum_snapshot_date_entry", table_name="etf_momentum_snapshot")
    op.drop_table("etf_momentum_snapshot")
