"""Replace portfolio and symbol domains with security master and universes.

Revision ID: 0039_unified_security
Revises: 0038_remove_legacy_minute
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_unified_security"
down_revision: Union[str, Sequence[str], None] = "0038_remove_legacy_minute"
branch_labels = None
depends_on = None

JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

SECURITY_FK_TABLES = (
    "stock_daily", "trend_following_snapshot", "etf_momentum_snapshot", "market_event",
    "event_feature_daily", "daily_feature_snapshot", "model_prediction", "model_signal",
    "portfolio_recommendation_item",
)

QUANT_DATA_TABLES = (
    "portfolio_recommendation_item",
    "portfolio_recommendation",
    "model_signal",
    "model_prediction",
    "model_publication",
    "model_run",
    "quant_dataset_snapshot",
    "daily_feature_snapshot",
    "event_feature_daily",
    "market_event",
    "market_regime_snapshot",
    "sector_regime_snapshot",
)

UNIVERSES = (
    ("cn_all_a", "全部A股", "CN", "MARKET"),
    ("cn_csi300", "沪深300", "CN", "INDEX"),
    ("cn_csi500", "中证500", "CN", "INDEX"),
    ("cn_csi1000", "中证1000", "CN", "INDEX"),
    ("us_sp500", "S&P 500", "US", "INDEX"),
    ("cn_trend", "A股趋势跟踪", "CN", "STRATEGY"),
    ("us_trend", "美股趋势跟踪", "US", "STRATEGY"),
    ("cn_etf_rotation", "A股ETF轮动", "CN", "STRATEGY"),
    ("us_etf_rotation", "美股ETF轮动", "US", "STRATEGY"),
    ("cn_quant", "A股量化", "CN", "STRATEGY"),
    ("us_quant", "美股量化", "US", "STRATEGY"),
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _constraint_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    names = {item.get("name") for item in inspector.get_unique_constraints(table)}
    names.update(item.get("name") for item in inspector.get_check_constraints(table))
    return {name for name in names if name}


def _index_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table) if item.get("name")}


def upgrade() -> None:
    tables = _tables()
    for table in ("position", "option_contract", "account_cash_balance", "portfolio_account"):
        if table in tables:
            op.drop_table(table)
    if "instrument" in tables:
        op.drop_table("instrument")

    quant_data_tables = [table for table in QUANT_DATA_TABLES if table in tables]
    if quant_data_tables:
        op.execute(sa.text(f"TRUNCATE TABLE {', '.join(quant_data_tables)} RESTART IDENTITY CASCADE"))

    op.rename_table("market_data_symbol", "instrument")
    if "ix_market_data_symbol_sync" in _index_names("instrument"):
        op.drop_index("ix_market_data_symbol_sync", table_name="instrument")
    with op.batch_alter_table("instrument") as batch:
        batch.add_column(sa.Column("native_code", sa.String(32)))
        batch.add_column(sa.Column("instrument_type", sa.String(16)))
        batch.add_column(sa.Column("currency", sa.String(8)))
        batch.add_column(sa.Column("listing_date", sa.Date()))
        batch.add_column(sa.Column("listing_status", sa.String(16)))
        batch.add_column(sa.Column("source", sa.String(32)))
        batch.add_column(sa.Column("metadata", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False))
    op.execute(sa.text("""
        UPDATE instrument SET
            native_code = split_part(code, '.', 1), instrument_type = 'STOCK',
            currency = CASE market WHEN 'CN' THEN 'CNY' WHEN 'HK' THEN 'HKD' ELSE 'USD' END,
            listing_status = 'ACTIVE', source = 'MIGRATION'
    """))
    with op.batch_alter_table("instrument") as batch:
        for column in ("native_code", "instrument_type", "currency", "listing_status", "source"):
            batch.alter_column(column, nullable=False)
        for column in ("enabled", "sync_daily"):
            if column in _columns("instrument"):
                batch.drop_column(column)
        constraints = _constraint_names("instrument")
        if "uix_market_data_symbol_market_code" in constraints:
            batch.drop_constraint("uix_market_data_symbol_market_code", type_="unique")
        if "uix_market_data_symbol_code" in constraints:
            batch.drop_constraint("uix_market_data_symbol_code", type_="unique")
        if "ck_market_data_symbol_code_suffix" in constraints:
            batch.drop_constraint("ck_market_data_symbol_code_suffix", type_="check")
        if "ck_market_data_symbol_market" in constraints:
            batch.drop_constraint("ck_market_data_symbol_market", type_="check")
        batch.create_unique_constraint("uix_instrument_code", ["code"])
        batch.create_check_constraint("ck_instrument_market", "market IN ('US','HK','CN')")
        batch.create_check_constraint(
            "ck_instrument_code_suffix",
            "(market = 'US' AND code LIKE '%.US') OR "
            "(market = 'HK' AND code ~ '^[1-9][0-9]*\\.HK$') OR "
            "(market = 'CN' AND code ~ '^[0-9]{6}\\.(SH|SZ|BJ)$')",
        )
        batch.create_check_constraint("ck_instrument_type", "instrument_type IN ('STOCK','ETF','INDEX')")
        batch.create_check_constraint("ck_instrument_currency", "currency IN ('CNY','USD','HKD')")
        batch.create_check_constraint("ck_instrument_listing_status", "listing_status IN ('ACTIVE','DELISTED')")
        batch.create_index("ix_instrument_market_type_status", ["market", "instrument_type", "listing_status"])

    for table in SECURITY_FK_TABLES:
        if table in _tables() and "symbol_id" in _columns(table):
            op.alter_column(table, "symbol_id", new_column_name="instrument_id")

    if "stock_daily" in _tables():
        with op.batch_alter_table("stock_daily") as batch:
            constraints = _constraint_names("stock_daily")
            if "uix_stock_daily_symbol_date" in constraints:
                batch.drop_constraint("uix_stock_daily_symbol_date", type_="unique")
            if "uix_stock_daily_instrument_date" not in constraints:
                batch.create_unique_constraint(
                    "uix_stock_daily_instrument_date", ["instrument_id", "date"]
                )

    if "quant_universe_member" in _tables():
        op.drop_table("quant_universe_member")

    if "quant_universe" in _tables():
        op.rename_table("quant_universe", "universe")
        with op.batch_alter_table("universe") as batch:
            batch.add_column(sa.Column("universe_type", sa.String(16), server_default="INDEX", nullable=False))
            for column in ("description", "is_dynamic", "benchmark_code", "sector_benchmark_mode"):
                if column in _columns("universe"):
                    batch.drop_column(column)
            constraints = _constraint_names("universe")
            if "ck_quant_universe_market" in constraints:
                batch.drop_constraint("ck_quant_universe_market", type_="check")
            batch.create_check_constraint("ck_universe_market", "market IN ('US','HK','CN')")
            batch.create_check_constraint(
                "ck_universe_type", "universe_type IN ('MARKET','INDEX','STRATEGY')"
            )
        op.execute(sa.text("TRUNCATE TABLE universe RESTART IDENTITY CASCADE"))
    else:
        op.create_table(
            "universe", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(128), nullable=False), sa.Column("market", sa.String(8), nullable=False),
            sa.Column("universe_type", sa.String(16), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("config", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    op.create_table(
        "universe_member", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("metadata", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("universe_id", "instrument_id", name="uix_universe_member"),
    )

    op.create_table(
        "universe_include", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="CASCADE"), nullable=False),
        sa.Column("included_universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("universe_id", "included_universe_id", name="uix_universe_include"),
        sa.CheckConstraint("universe_id <> included_universe_id", name="ck_universe_include_not_self"),
    )

    connection = op.get_bind()
    for key, name, market, universe_type in UNIVERSES:
        connection.execute(sa.text("""
            INSERT INTO universe (key, name, market, universe_type, enabled, config, created_at, updated_at)
            VALUES (:key, :name, :market, :universe_type, true, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name, universe_type=EXCLUDED.universe_type
        """), {"key": key, "name": name, "market": market, "universe_type": universe_type})
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("""
            SELECT setval(pg_get_serial_sequence('instrument', 'id'),
                          COALESCE((SELECT MAX(id) FROM instrument), 1), true)
        """))


def downgrade() -> None:
    raise NotImplementedError("The portfolio sunset and security-master migration are intentionally irreversible")
