# -*- coding: utf-8 -*-
"""Add market type to watch and stock lists.

Revision ID: 0004_watch_stock_market_type
Revises: 0003_users_username_not_unique
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_watch_stock_market_type"
down_revision: Union[str, Sequence[str], None] = "0003_users_username_not_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("watch_list", "stock_list"):
        op.add_column(
            table_name,
            sa.Column("market_type", sa.String(length=8), nullable=False, server_default="CN"),
        )
        op.create_index(op.f(f"ix_{table_name}_market_type"), table_name, ["market_type"], unique=False)
        op.alter_column(table_name, "market_type", server_default=None)


def downgrade() -> None:
    for table_name in ("stock_list", "watch_list"):
        op.drop_index(op.f(f"ix_{table_name}_market_type"), table_name=table_name)
        op.drop_column(table_name, "market_type")
