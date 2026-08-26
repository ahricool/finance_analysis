"""Add volatility-based stop-loss metadata to ETF rotation snapshots.

Revision ID: 0029_etf_rotation_stop_loss
Revises: 0028_etf_rotation_market
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_etf_rotation_stop_loss"
down_revision: Union[str, Sequence[str], None] = "0028_etf_rotation_market"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Historical snapshots remain nullable: the values were not generated as
    # part of those point-in-time evaluations and should not be fabricated.
    op.add_column("etf_momentum_snapshot", sa.Column("reference_price", sa.Float(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("stop_loss_pct", sa.Float(), nullable=True))
    op.add_column("etf_momentum_snapshot", sa.Column("suggested_stop_price", sa.Float(), nullable=True))
    constraints = (
        ("ck_etf_reference_price_positive", "reference_price IS NULL OR reference_price > 0"),
        (
            "ck_etf_stop_loss_pct_range",
            "stop_loss_pct IS NULL OR (stop_loss_pct >= 0 AND stop_loss_pct < 1)",
        ),
        (
            "ck_etf_suggested_stop_price_positive",
            "suggested_stop_price IS NULL OR "
            "(suggested_stop_price > 0 AND reference_price IS NOT NULL AND suggested_stop_price <= reference_price)",
        ),
        (
            "ck_etf_stop_loss_metadata_complete",
            "(reference_price IS NULL AND stop_loss_pct IS NULL AND suggested_stop_price IS NULL) OR "
            "(reference_price IS NOT NULL AND stop_loss_pct IS NOT NULL AND suggested_stop_price IS NOT NULL)",
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("etf_momentum_snapshot") as batch_op:
            for name, condition in constraints:
                batch_op.create_check_constraint(name, condition)
    else:
        for name, condition in constraints:
            op.create_check_constraint(name, "etf_momentum_snapshot", condition)


def downgrade() -> None:
    constraint_names = (
        "ck_etf_stop_loss_metadata_complete",
        "ck_etf_suggested_stop_price_positive",
        "ck_etf_stop_loss_pct_range",
        "ck_etf_reference_price_positive",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("etf_momentum_snapshot") as batch_op:
            for name in constraint_names:
                batch_op.drop_constraint(name, type_="check")
            batch_op.drop_column("suggested_stop_price")
            batch_op.drop_column("stop_loss_pct")
            batch_op.drop_column("reference_price")
    else:
        for name in constraint_names:
            op.drop_constraint(name, "etf_momentum_snapshot", type_="check")
        op.drop_column("etf_momentum_snapshot", "suggested_stop_price")
        op.drop_column("etf_momentum_snapshot", "stop_loss_pct")
        op.drop_column("etf_momentum_snapshot", "reference_price")
