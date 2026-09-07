"""BTCUSDT minute facts and strategy state/snapshots.

Revision ID: 0044_crypto_btc
Revises: 0043_investment_timeline
"""

from alembic import op
import sqlalchemy as sa

revision = "0044_crypto_btc"
down_revision = "0043_investment_timeline"
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_table(
        "crypto_strategy_state",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("position_state", sa.String(8), nullable=False),
        sa.Column("entry_price", sa.Numeric(30, 12)),
        sa.Column("entry_time", sa.DateTime(timezone=True)),
        sa.Column("highest_price_since_entry", sa.Numeric(30, 12)),
        sa.Column("initial_stop", sa.Numeric(30, 12)),
        sa.Column("trailing_stop", sa.Numeric(30, 12)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position_state IN ('FLAT', 'LONG')", name="ck_crypto_state_position"),
    )
    op.create_table(
        "crypto_strategy_snapshot",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regime", sa.String(16), nullable=False),
        sa.Column("setup", sa.String(16), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("price", sa.Numeric(30, 12), nullable=False),
        sa.Column("ema20_1h", sa.Numeric(30, 12)),
        sa.Column("ema50_1h", sa.Numeric(30, 12)),
        sa.Column("ema20_15m", sa.Numeric(30, 12)),
        sa.Column("breakout_level_15m", sa.Numeric(30, 12)),
        sa.Column("volume_ratio_15m", sa.Numeric(30, 12)),
        sa.Column("atr14_15m", sa.Numeric(30, 12)),
        sa.Column("initial_stop", sa.Numeric(30, 12)),
        sa.Column("trailing_stop", sa.Numeric(30, 12)),
        sa.Column("position_state", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "evaluated_at", name="uq_crypto_snapshot_symbol_evaluated"),
    )


def downgrade():
    op.drop_table("crypto_strategy_snapshot")
    op.drop_table("crypto_strategy_state")
    op.drop_table("crypto_kline")
