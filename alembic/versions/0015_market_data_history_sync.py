"""Canonical symbols and raw daily/minute market data.

Revision ID: 0015_market_data_history
Revises: 0014_rename_us_signal_type
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_market_data_history"
down_revision: Union[str, Sequence[str], None] = "0014_rename_us_signal_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_symbol_table() -> None:
    op.create_table(
        "market_data_symbol",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sync_daily", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sync_minute", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("market IN ('US', 'HK', 'CN')", name="ck_market_data_symbol_market"),
        sa.CheckConstraint(
            "(market = 'US' AND code LIKE '%.US') OR "
            "(market = 'HK' AND code ~ '^[1-9][0-9]*\\.HK$') OR "
            "(market = 'CN' AND code ~ '^[0-9]{6}\\.(SH|SZ)$')",
            name="ck_market_data_symbol_code_suffix",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uix_market_data_symbol_code"),
        sa.UniqueConstraint("market", "code", name="uix_market_data_symbol_market_code"),
    )
    op.create_index("ix_market_data_symbol_market", "market_data_symbol", ["market"])
    op.create_index(
        "ix_market_data_symbol_sync",
        "market_data_symbol",
        ["market", "enabled", "sync_daily", "sync_minute"],
    )


def _create_daily_table() -> None:
    op.create_table(
        "stock_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("data_source", sa.String(length=50), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("volume >= 0", name="ck_stock_daily_volume_nonnegative"),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_stock_daily_amount_nonnegative"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", "date", name="uix_stock_daily_symbol_date"),
    )
    op.create_index("ix_stock_daily_symbol_date", "stock_daily", ["symbol_id", "date"])


def _create_minute_table() -> None:
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
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("session_type", sa.String(length=16), server_default="regular", nullable=False),
        sa.Column("data_source", sa.String(length=50), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("volume >= 0", name="ck_stock_minute_volume_nonnegative"),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_stock_minute_amount_nonnegative"),
        sa.CheckConstraint("session_type = 'regular'", name="ck_stock_minute_regular_session"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", "bar_time", name="uix_stock_minute_symbol_time"),
    )
    op.create_index("ix_stock_minute_symbol_time", "stock_minute", ["symbol_id", "bar_time"])


def _canonical_code_sql() -> str:
    return """
    CASE
      WHEN upper(d.market) = 'US' THEN upper(regexp_replace(d.code, '\\.US$', '', 'i')) || '.US'
      WHEN upper(d.market) = 'HK' THEN
        (CASE WHEN regexp_replace(upper(d.code), '^(HK)?0*|\\.HK$', '', 'g') = '' THEN '0'
              ELSE regexp_replace(upper(d.code), '^(HK)?0*|\\.HK$', '', 'g') END) || '.HK'
      WHEN upper(d.market) = 'CN' THEN
        regexp_replace(upper(d.code), '^(SH|SZ)|\\.(SH|SS|SZ)$', '', 'g') ||
        CASE WHEN regexp_replace(upper(d.code), '^(SH|SZ)|\\.(SH|SS|SZ)$', '', 'g') ~ '^[659]'
             THEN '.SH' ELSE '.SZ' END
      ELSE NULL
    END
    """


def _migrate_legacy_daily() -> None:
    canonical = _canonical_code_sql()
    op.execute(
        sa.text(
            f"""
            INSERT INTO market_data_symbol (market, code, name, enabled, sync_daily, sync_minute, created_at, updated_at)
            SELECT DISTINCT upper(market), {canonical}, {canonical}, true, true, true, now(), now()
            FROM stock_daily_legacy d
            WHERE upper(d.market) IN ('US', 'HK', 'CN') AND {canonical} IS NOT NULL
            ON CONFLICT (code) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO stock_daily
                (symbol_id, date, open, high, low, close, volume, amount,
                 data_source, source_priority, created_at, updated_at)
            SELECT s.id, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount,
                   COALESCE(NULLIF(d.data_source, ''), 'legacy'),
                   CASE WHEN lower(COALESCE(d.data_source, '')) LIKE '%longbridge%' THEN 100
                        WHEN lower(COALESCE(d.data_source, '')) LIKE '%yfinance%' THEN 50 ELSE 10 END,
                   COALESCE(d.created_at, now()), COALESCE(d.updated_at, now())
            FROM stock_daily_legacy d
            JOIN market_data_symbol s ON s.code = {canonical}
            WHERE d.date IS NOT NULL
              AND d.open > 0 AND d.high > 0 AND d.low > 0 AND d.close > 0
              AND d.high >= d.open AND d.high >= d.close AND d.high >= d.low
              AND d.low <= d.open AND d.low <= d.close
              AND d.volume >= 0 AND (d.amount IS NULL OR d.amount >= 0)
            ON CONFLICT (symbol_id, date) DO UPDATE SET
              open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
              close = EXCLUDED.close, volume = EXCLUDED.volume, amount = EXCLUDED.amount,
              data_source = EXCLUDED.data_source, source_priority = EXCLUDED.source_priority,
              updated_at = EXCLUDED.updated_at
            WHERE EXCLUDED.source_priority >= stock_daily.source_priority
            """
        )
    )
    op.execute(
        sa.text(
            """DO $$
            DECLARE dropped_count bigint;
            BEGIN
              SELECT count(*) INTO dropped_count FROM stock_daily_legacy d
              WHERE upper(COALESCE(d.market, '')) NOT IN ('US','HK','CN')
                 OR d.date IS NULL OR d.open <= 0 OR d.high <= 0 OR d.low <= 0 OR d.close <= 0
                 OR d.high < d.open OR d.high < d.close OR d.high < d.low
                 OR d.low > d.open OR d.low > d.close OR d.volume < 0 OR d.volume IS NULL
                 OR (d.amount IS NOT NULL AND d.amount < 0);
              IF dropped_count > 0 THEN
                RAISE WARNING 'market data migration skipped % invalid/unrecognized stock_daily rows', dropped_count;
              END IF;
            END $$"""
        )
    )
    op.drop_table("stock_daily_legacy")


def _seed_nasdaq100() -> None:
    from finance_analysis.stocks.reference_data.stock_index import NASDAQ100_STOCK_INDEX

    table = sa.table(
        "market_data_symbol",
        sa.column("market", sa.String), sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("enabled", sa.Boolean), sa.column("sync_daily", sa.Boolean), sa.column("sync_minute", sa.Boolean),
    )
    bind = op.get_bind()
    stmt = postgresql.insert(table).values(
        [
            {
                "market": "US", "code": f"{ticker}.US", "name": name,
                "enabled": True, "sync_daily": True, "sync_minute": True,
            }
            for ticker, name in NASDAQ100_STOCK_INDEX.items()
        ]
    )
    bind.execute(stmt.on_conflict_do_update(index_elements=["code"], set_={"name": stmt.excluded.name}))


def _add_active_task_dedupe_constraint(inspector: sa.Inspector) -> None:
    indexes = {item["name"] for item in inspector.get_indexes("task")}
    if "uix_task_active_dedupe" in indexes:
        return
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (PARTITION BY dedupe_key ORDER BY created_at DESC, id DESC) AS rn
          FROM task
          WHERE dedupe_key IS NOT NULL AND status IN ('pending','processing','retrying')
        )
        UPDATE task SET status='skipped', message='superseded while adding active dedupe constraint',
                        progress=100, finished_at=now(), updated_at=now()
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    op.create_index(
        "uix_task_active_dedupe",
        "task",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('pending','processing','retrying')"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "market_data_symbol" not in tables:
        _create_symbol_table()
    if "stock_daily" in tables:
        daily_columns = {item["name"] for item in inspector.get_columns("stock_daily")}
        if "symbol_id" not in daily_columns:
            op.rename_table("stock_daily", "stock_daily_legacy")
            _create_daily_table()
            _migrate_legacy_daily()
    else:
        _create_daily_table()
    inspector = sa.inspect(bind)
    if "stock_minute" not in inspector.get_table_names():
        _create_minute_table()
    _seed_nasdaq100()
    _add_active_task_dedupe_constraint(sa.inspect(bind))


def downgrade() -> None:
    raise NotImplementedError("Destructive raw market-data migration cannot be downgraded safely")
