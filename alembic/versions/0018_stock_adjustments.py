"""Add corporate actions and daily adjustment factors.

Revision ID: 0018_stock_adjustments
Revises: 0017_quant_research
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_stock_adjustments"
down_revision: Union[str, Sequence[str], None] = "0017_quant_research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_corporate_actions() -> None:
    op.create_table(
        "stock_corporate_action",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("action_date", sa.Date(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("cash_dividend", sa.Float(), nullable=True),
        sa.Column("split_ratio", sa.Float(), nullable=True),
        sa.Column("bonus_ratio", sa.Float(), nullable=True),
        sa.Column("rights_ratio", sa.Float(), nullable=True),
        sa.Column("rights_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_source", sa.String(length=50), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('dividend', 'split', 'bonus', 'rights')",
            name="ck_stock_corporate_action_type",
        ),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol_id",
            "action_date",
            "action_type",
            name="uix_stock_corporate_action_symbol_date_type",
        ),
    )
    op.create_index(
        "ix_stock_corporate_action_symbol_date",
        "stock_corporate_action",
        ["symbol_id", "action_date"],
    )


def _create_adjustment_factors() -> None:
    op.create_table(
        "stock_adjustment_factor",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("qfq_factor", sa.Float(), nullable=True),
        sa.Column("hfq_factor", sa.Float(), nullable=True),
        sa.Column("hfq_cash", sa.Float(), nullable=True),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.Column("data_source", sa.String(length=50), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "qfq_factor IS NULL OR qfq_factor > 0",
            name="ck_stock_adjustment_qfq_positive",
        ),
        sa.CheckConstraint(
            "hfq_factor IS NULL OR hfq_factor > 0",
            name="ck_stock_adjustment_hfq_positive",
        ),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol_id",
            "trade_date",
            name="uix_stock_adjustment_factor_symbol_date",
        ),
    )
    op.create_index(
        "ix_stock_adjustment_factor_symbol_date",
        "stock_adjustment_factor",
        ["symbol_id", "trade_date"],
    )


def upgrade() -> None:
    # The collapsed 0001 baseline creates current ORM metadata on new databases.
    # These guards keep the documented baseline-then-stamp bootstrap path safe,
    # while still creating both tables on an existing 0017 production database.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "stock_corporate_action" not in tables:
        _create_corporate_actions()
    if "stock_adjustment_factor" not in tables:
        _create_adjustment_factors()


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "stock_adjustment_factor" in tables:
        op.drop_index("ix_stock_adjustment_factor_symbol_date", table_name="stock_adjustment_factor")
        op.drop_table("stock_adjustment_factor")
    if "stock_corporate_action" in tables:
        op.drop_index("ix_stock_corporate_action_symbol_date", table_name="stock_corporate_action")
        op.drop_table("stock_corporate_action")
