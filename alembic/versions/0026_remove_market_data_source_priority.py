"""Remove integer market-data source priorities.

Revision ID: 0026_remove_source_priority
Revises: 0025_portfolio_accounts
Create Date: 2026-07-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0026_remove_source_priority"
down_revision: Union[str, Sequence[str], None] = "0025_portfolio_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for table_name in ("stock_daily", "stock_minute"):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "source_priority" in columns:
            op.drop_column(table_name, "source_priority")


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    for table_name in ("stock_minute", "stock_daily"):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "source_priority" not in columns:
            op.add_column(table_name, sa.Column("source_priority", sa.Integer(), nullable=False, server_default="0"))
