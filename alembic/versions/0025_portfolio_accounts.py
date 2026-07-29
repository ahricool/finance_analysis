"""Replace legacy stock holdings with fixed portfolio accounts.

Revision ID: 0025_portfolio_accounts
Revises: 0024_quant_market_dependencies
Create Date: 2026-07-29

This migration intentionally discards all legacy ``stock_list`` rows. The old
holdings schema is not compatible with the account/instrument model and no data
conversion is performed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision: str = "0025_portfolio_accounts"
down_revision: Union[str, Sequence[str], None] = "0024_quant_market_dependencies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _create_tables() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    if not _table_exists("portfolio_account"):
        op.create_table(
            "portfolio_account",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("uid", sa.Integer(), nullable=False),
            sa.Column("account_code", sa.String(length=8), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("market", sa.String(length=8), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("account_code IN ('CN', 'HK', 'US')", name="ck_portfolio_account_code"),
            sa.CheckConstraint("market IN ('CN', 'HK', 'US')", name="ck_portfolio_account_market"),
            sa.CheckConstraint("currency IN ('CNY', 'HKD', 'USD')", name="ck_portfolio_account_currency"),
            sa.CheckConstraint(
                "(account_code = 'CN' AND name = 'A股账户' AND market = 'CN' AND currency = 'CNY') OR "
                "(account_code = 'HK' AND name = '港股账户' AND market = 'HK' AND currency = 'HKD') OR "
                "(account_code = 'US' AND name = '美股账户' AND market = 'US' AND currency = 'USD')",
                name="ck_portfolio_account_identity",
            ),
            sa.ForeignKeyConstraint(["uid"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("uid", "account_code", name="uix_portfolio_account_uid_code"),
            sa.UniqueConstraint("uid", "market", name="uix_portfolio_account_uid_market"),
        )
        op.create_index("ix_portfolio_account_uid", "portfolio_account", ["uid"])

    if not _table_exists("account_cash_balance"):
        op.create_table(
            "account_cash_balance",
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("balance", sa.Numeric(24, 8), server_default=sa.text("0"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["portfolio_account.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("account_id"),
        )

    if not _table_exists("instrument"):
        op.create_table(
            "instrument",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("asset_type", sa.String(length=16), nullable=False),
            sa.Column("market", sa.String(length=8), nullable=False),
            sa.Column("canonical_symbol", sa.String(length=128), nullable=False),
            sa.Column("display_symbol", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("contract_multiplier", sa.Numeric(24, 8), server_default=sa.text("1"), nullable=False),
            sa.Column("market_data_symbol_id", sa.Integer(), nullable=True),
            sa.Column("extra", json_type, server_default=sa.text("'{}'"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("asset_type IN ('STOCK', 'ETF', 'OPTION')", name="ck_instrument_asset_type"),
            sa.CheckConstraint("market IN ('CN', 'HK', 'US')", name="ck_instrument_market"),
            sa.CheckConstraint("currency IN ('CNY', 'HKD', 'USD')", name="ck_instrument_currency"),
            sa.CheckConstraint("contract_multiplier > 0", name="ck_instrument_multiplier_positive"),
            sa.CheckConstraint(
                "(market = 'CN' AND currency = 'CNY') OR "
                "(market = 'HK' AND currency = 'HKD') OR "
                "(market = 'US' AND currency = 'USD')",
                name="ck_instrument_market_currency",
            ),
            sa.CheckConstraint(
                "asset_type = 'OPTION' OR contract_multiplier = 1",
                name="ck_instrument_equity_multiplier",
            ),
            sa.CheckConstraint(
                "asset_type != 'OPTION' OR "
                "(market = 'US' AND currency = 'USD' AND market_data_symbol_id IS NULL)",
                name="ck_instrument_option_identity",
            ),
            sa.ForeignKeyConstraint(
                ["market_data_symbol_id"], ["market_data_symbol.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "market", "asset_type", "canonical_symbol", name="uix_instrument_market_type_symbol"
            ),
        )
        op.create_index("ix_instrument_asset_type", "instrument", ["asset_type"])
        op.create_index("ix_instrument_market", "instrument", ["market"])
        op.create_index("ix_instrument_market_data_symbol_id", "instrument", ["market_data_symbol_id"])

    if not _table_exists("option_contract"):
        op.create_table(
            "option_contract",
            sa.Column("instrument_id", sa.Integer(), nullable=False),
            sa.Column("underlying_instrument_id", sa.Integer(), nullable=False),
            sa.Column("expiration_date", sa.Date(), nullable=False),
            sa.Column("strike_price", sa.Numeric(24, 8), nullable=False),
            sa.Column("option_type", sa.String(length=4), nullable=False),
            sa.CheckConstraint("strike_price > 0", name="ck_option_contract_strike_positive"),
            sa.CheckConstraint("option_type IN ('CALL', 'PUT')", name="ck_option_contract_type"),
            sa.ForeignKeyConstraint(["instrument_id"], ["instrument.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["underlying_instrument_id"], ["instrument.id"]),
            sa.PrimaryKeyConstraint("instrument_id"),
            sa.UniqueConstraint(
                "underlying_instrument_id",
                "expiration_date",
                "strike_price",
                "option_type",
                name="uix_option_contract_identity",
            ),
        )
        op.create_index("ix_option_contract_underlying_instrument_id", "option_contract", ["underlying_instrument_id"])

    if not _table_exists("position"):
        op.create_table(
            "position",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("instrument_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
            sa.Column("avg_cost", sa.Numeric(24, 8), nullable=False),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=16), server_default=sa.text("'OPEN'"), nullable=False),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("quantity <> 0", name="ck_position_quantity_nonzero"),
            sa.CheckConstraint("avg_cost >= 0", name="ck_position_avg_cost_nonnegative"),
            sa.CheckConstraint("status IN ('OPEN', 'CLOSED', 'EXPIRED')", name="ck_position_status"),
            sa.CheckConstraint(
                "(status = 'OPEN' AND closed_at IS NULL) OR status IN ('CLOSED', 'EXPIRED')",
                name="ck_position_open_closed_at",
            ),
            sa.ForeignKeyConstraint(["account_id"], ["portfolio_account.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["instrument_id"], ["instrument.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "instrument_id", name="uix_position_account_instrument"),
        )
        op.create_index("ix_position_account_id", "position", ["account_id"])
        op.create_index("ix_position_instrument_id", "position", ["instrument_id"])
        op.create_index("ix_position_status", "position", ["status"])


def _seed_fixed_accounts() -> None:
    bind = op.get_bind()
    now_sql = "CURRENT_TIMESTAMP"
    definitions = (
        ("CN", "A股账户", "CN", "CNY"),
        ("HK", "港股账户", "HK", "HKD"),
        ("US", "美股账户", "US", "USD"),
    )
    for code, name, market, currency in definitions:
        bind.execute(
            sa.text(
                "INSERT INTO portfolio_account "
                "(uid, account_code, name, market, currency, created_at, updated_at) "
                f"SELECT id, :code, :name, :market, :currency, {now_sql}, {now_sql} FROM users "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM portfolio_account pa "
                "WHERE pa.uid = users.id AND pa.account_code = :code)"
            ),
            {"code": code, "name": name, "market": market, "currency": currency},
        )
    bind.execute(
        sa.text(
            "INSERT INTO account_cash_balance (account_id, balance, updated_at) "
            f"SELECT id, 0, {now_sql} FROM portfolio_account "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM account_cash_balance cb WHERE cb.account_id = portfolio_account.id)"
        )
    )


def upgrade() -> None:
    _create_tables()
    _seed_fixed_accounts()
    if _table_exists("stock_list"):
        # Destructive by design: legacy holdings are deliberately not migrated.
        op.drop_table("stock_list")


def downgrade() -> None:
    for table in ("position", "option_contract", "instrument", "account_cash_balance", "portfolio_account"):
        if _table_exists(table):
            op.drop_table(table)

    # Restore only an empty legacy shape so older revisions can be traversed.
    # Deleted holding data is intentionally unrecoverable.
    if not _table_exists("stock_list"):
        op.create_table(
            "stock_list",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("uid", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=16), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=True),
            sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
            sa.Column("avg_cost", sa.Numeric(24, 8), nullable=True),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("market_type", sa.String(length=8), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("uid", "market_type", "code", name="uix_stock_list_uid_market_code"),
        )
        op.create_index("ix_stock_list_uid", "stock_list", ["uid"])
        op.create_index("ix_stock_list_code", "stock_list", ["code"])
        op.create_index("ix_stock_list_market_type", "stock_list", ["market_type"])
