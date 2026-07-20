"""Add persisted daily VWAP metadata.

Revision ID: 0019_stock_daily_vwap
Revises: 0018_stock_adjustments
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_stock_daily_vwap"
down_revision: Union[str, Sequence[str], None] = "0018_stock_adjustments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("stock_daily")}
    if "vwap" not in columns:
        op.add_column("stock_daily", sa.Column("vwap", sa.Float(), nullable=True))
    if "vwap_source" not in columns:
        op.add_column("stock_daily", sa.Column("vwap_source", sa.String(length=32), nullable=True))
    if "vwap_quality" not in columns:
        op.add_column("stock_daily", sa.Column("vwap_quality", sa.String(length=16), nullable=True))

    constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints("stock_daily")}
    if "ck_stock_daily_vwap_positive" not in constraints:
        op.create_check_constraint("ck_stock_daily_vwap_positive", "stock_daily", "vwap IS NULL OR vwap > 0")
    if "ck_stock_daily_vwap_quality" not in constraints:
        op.create_check_constraint(
            "ck_stock_daily_vwap_quality",
            "stock_daily",
            "vwap_quality IS NULL OR vwap_quality IN ('provider', 'calculated', 'estimated', 'missing')",
        )


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("stock_daily")}
    constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints("stock_daily")}
    if "ck_stock_daily_vwap_quality" in constraints:
        op.drop_constraint("ck_stock_daily_vwap_quality", "stock_daily", type_="check")
    if "ck_stock_daily_vwap_positive" in constraints:
        op.drop_constraint("ck_stock_daily_vwap_positive", "stock_daily", type_="check")
    for column in ("vwap_quality", "vwap_source", "vwap"):
        if column in columns:
            op.drop_column("stock_daily", column)
