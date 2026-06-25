"""Support decimal holdings and market-scoped stock identity.

Revision ID: 0010_holdings_decimal_cost
Revises: 0009_event_importance
Create Date: 2026-06-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0010_holdings_decimal_cost"
down_revision: Union[str, Sequence[str], None] = "0009_event_importance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "stock_list",
        "quantity",
        existing_type=sa.Integer(),
        type_=sa.Numeric(24, 8),
        existing_nullable=False,
        postgresql_using="quantity::numeric",
    )
    op.add_column("stock_list", sa.Column("avg_cost", sa.Numeric(24, 8), nullable=True))
    op.add_column("stock_list", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))

    op.drop_constraint("uix_watch_list_uid_code", "watch_list", type_="unique")
    op.create_unique_constraint(
        "uix_watch_list_uid_market_code",
        "watch_list",
        ["uid", "market_type", "code"],
    )

    op.drop_constraint("uix_stock_list_uid_code", "stock_list", type_="unique")
    op.create_unique_constraint(
        "uix_stock_list_uid_market_code",
        "stock_list",
        ["uid", "market_type", "code"],
    )


def downgrade() -> None:
    op.drop_constraint("uix_stock_list_uid_market_code", "stock_list", type_="unique")
    op.create_unique_constraint("uix_stock_list_uid_code", "stock_list", ["uid", "code"])

    op.drop_constraint("uix_watch_list_uid_market_code", "watch_list", type_="unique")
    op.create_unique_constraint("uix_watch_list_uid_code", "watch_list", ["uid", "code"])

    op.drop_column("stock_list", "opened_at")
    op.drop_column("stock_list", "avg_cost")
    op.alter_column(
        "stock_list",
        "quantity",
        existing_type=sa.Numeric(24, 8),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="quantity::integer",
    )
