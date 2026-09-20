"""Remove stored Binance candles; preserve strategy state and snapshots.

Downgrade recreates an empty candle table; deleted market history is not restored.
"""

import sqlalchemy as sa

from alembic import op

revision = "0059_drop_crypto_kline"
down_revision = "0058_industry_constituents"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("crypto_kline")


def downgrade():
    op.create_table(
        "crypto_kline",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("interval", sa.String(4), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(30, 12), nullable=False),
        sa.Column("high", sa.Numeric(30, 12), nullable=False),
        sa.Column("low", sa.Numeric(30, 12), nullable=False),
        sa.Column("close", sa.Numeric(30, 12), nullable=False),
        sa.Column("volume", sa.Numeric(30, 12), nullable=False),
        sa.Column("quote_volume", sa.Numeric(30, 12), nullable=False),
        sa.Column("trade_count", sa.Integer, nullable=False),
        sa.Column("taker_buy_volume", sa.Numeric(30, 12), nullable=False),
        sa.Column("taker_buy_quote_volume", sa.Numeric(30, 12), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "interval", "open_time", name="uq_crypto_kline_symbol_interval_open"),
        sa.CheckConstraint(
            "symbol = 'BTCUSDT' AND interval = '1m' AND source = 'binance'", name="ck_crypto_kline_scope"
        ),
    )
