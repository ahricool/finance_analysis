"""Remove legacy minute persistence and quant intraday confirmation.

Revision ID: 0038_remove_legacy_minute
Revises: 0037_forward_adjusted_daily
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_remove_legacy_minute"
down_revision: Union[str, Sequence[str], None] = "0037_forward_adjusted_daily"
branch_labels = None
depends_on = None

JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    tables = _tables()

    if "intraday_confirmation" in tables:
        op.drop_table("intraday_confirmation")
    if "stock_minute" in tables:
        op.drop_table("stock_minute")

    if "trend_following_snapshot" in tables and "intraday_confirmation" in _columns(
        "trend_following_snapshot"
    ):
        op.drop_column("trend_following_snapshot", "intraday_confirmation")

    if "market_data_symbol" in tables and "sync_minute" in _columns("market_data_symbol"):
        if "ix_market_data_symbol_sync" in _indexes("market_data_symbol"):
            op.drop_index("ix_market_data_symbol_sync", table_name="market_data_symbol")
        op.drop_column("market_data_symbol", "sync_minute")
        op.create_index(
            "ix_market_data_symbol_sync",
            "market_data_symbol",
            ["market", "enabled", "sync_daily"],
        )


def downgrade() -> None:
    tables = _tables()

    if "market_data_symbol" in tables and "sync_minute" not in _columns("market_data_symbol"):
        if "ix_market_data_symbol_sync" in _indexes("market_data_symbol"):
            op.drop_index("ix_market_data_symbol_sync", table_name="market_data_symbol")
        op.add_column(
            "market_data_symbol",
            sa.Column("sync_minute", sa.Boolean(), server_default=sa.true(), nullable=False),
        )
        op.create_index(
            "ix_market_data_symbol_sync",
            "market_data_symbol",
            ["market", "enabled", "sync_daily", "sync_minute"],
        )

    if "stock_minute" not in tables:
        op.create_table(
            "stock_minute",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("symbol_id", sa.Integer(), nullable=False),
            sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("open", sa.Float(), nullable=False),
            sa.Column("high", sa.Float(), nullable=False),
            sa.Column("low", sa.Float(), nullable=False),
            sa.Column("close", sa.Float(), nullable=False),
            sa.Column("volume", sa.Float(), nullable=False),
            sa.Column("amount", sa.Float()),
            sa.Column("session_type", sa.String(16), nullable=False),
            sa.Column("data_source", sa.String(50), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("volume >= 0", name="ck_stock_minute_volume_nonnegative"),
            sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_stock_minute_amount_nonnegative"),
            sa.CheckConstraint("session_type = 'regular'", name="ck_stock_minute_regular_session"),
            sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol_id", "bar_time", name="uix_stock_minute_symbol_time"),
        )
        op.create_index(
            "ix_stock_minute_symbol_time",
            "stock_minute",
            ["symbol_id", "bar_time"],
        )

    if "intraday_confirmation" not in tables:
        op.create_table(
            "intraday_confirmation",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("symbol_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("recommendation_item_id", sa.BigInteger(), nullable=False),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decision", sa.String(24), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("price", sa.Float()),
            sa.Column("vwap", sa.Float()),
            sa.Column("price_vs_vwap", sa.Float()),
            sa.Column("vwap_slope", sa.Float()),
            sa.Column("first_30m_return", sa.Float()),
            sa.Column("intraday_high_drawdown", sa.Float()),
            sa.Column("volume_ratio", sa.Float()),
            sa.Column("relative_strength_market", sa.Float()),
            sa.Column("relative_strength_sector", sa.Float()),
            sa.Column("reasons", JSON_TYPE, nullable=False),
            sa.Column("features", JSON_TYPE, nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "decision IN ('confirm','wait','reject','expired','insufficient_data')",
                name="ck_intraday_decision",
            ),
            sa.ForeignKeyConstraint(
                ["recommendation_item_id"],
                ["portfolio_recommendation_item.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_intraday_latest",
            "intraday_confirmation",
            ["trade_date", "symbol_id", "evaluated_at"],
        )

    if "trend_following_snapshot" in tables and "intraday_confirmation" not in _columns(
        "trend_following_snapshot"
    ):
        op.add_column(
            "trend_following_snapshot",
            sa.Column(
                "intraday_confirmation",
                sa.String(16),
                server_default="UNAVAILABLE",
                nullable=False,
            ),
        )
