"""Add explicit market isolation to ETF rotation snapshots.

Revision ID: 0028_etf_rotation_market
Revises: 0027_etf_momentum_snapshot
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_etf_rotation_market"
down_revision: Union[str, Sequence[str], None] = "0027_etf_momentum_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("etf_momentum_snapshot", sa.Column("market", sa.String(length=8), nullable=True))
    op.execute("UPDATE etf_momentum_snapshot SET market = 'CN' WHERE market IS NULL")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("etf_momentum_snapshot") as batch_op:
            batch_op.alter_column("market", existing_type=sa.String(length=8), nullable=False)
            batch_op.create_check_constraint(
                "ck_etf_momentum_snapshot_market",
                "market IN ('CN', 'US')",
            )
    else:
        op.alter_column("etf_momentum_snapshot", "market", existing_type=sa.String(length=8), nullable=False)
        op.create_check_constraint(
            "ck_etf_momentum_snapshot_market",
            "etf_momentum_snapshot",
            "market IN ('CN', 'US')",
        )
    op.drop_index("ix_etf_momentum_snapshot_date_entry", table_name="etf_momentum_snapshot")
    op.drop_index("ix_etf_momentum_snapshot_date_candidate", table_name="etf_momentum_snapshot")
    op.create_index(
        "ix_etf_momentum_snapshot_market_date_entry",
        "etf_momentum_snapshot",
        ["market", "trade_date", "entry_score"],
    )
    op.create_index(
        "ix_etf_momentum_snapshot_market_date_candidate",
        "etf_momentum_snapshot",
        ["market", "trade_date", "is_candidate", "candidate_rank"],
    )


def downgrade() -> None:
    op.drop_index("ix_etf_momentum_snapshot_market_date_candidate", table_name="etf_momentum_snapshot")
    op.drop_index("ix_etf_momentum_snapshot_market_date_entry", table_name="etf_momentum_snapshot")
    op.create_index(
        "ix_etf_momentum_snapshot_date_candidate",
        "etf_momentum_snapshot",
        ["trade_date", "is_candidate", "candidate_rank"],
    )
    op.create_index(
        "ix_etf_momentum_snapshot_date_entry",
        "etf_momentum_snapshot",
        ["trade_date", "entry_score"],
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("etf_momentum_snapshot") as batch_op:
            batch_op.drop_constraint("ck_etf_momentum_snapshot_market", type_="check")
            batch_op.drop_column("market")
    else:
        op.drop_constraint("ck_etf_momentum_snapshot_market", "etf_momentum_snapshot", type_="check")
        op.drop_column("etf_momentum_snapshot", "market")
