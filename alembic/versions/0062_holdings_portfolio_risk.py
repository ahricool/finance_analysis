"""DB portfolio and Trade Engine LLM state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB  # pragma: allowlist secret

revision = "0062_holdings_portfolio_risk"
down_revision = "0061_crypto_strategy_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portfolio_account",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("cash", sa.Numeric(28, 8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_portfolio_account_market"),
        sa.CheckConstraint("cash >= 0", name="ck_portfolio_account_cash"),
        sa.UniqueConstraint("uid", "market", "name", name="uix_portfolio_account_uid_market_name"),
    )
    op.create_index("ix_portfolio_account_uid", "portfolio_account", ["uid"])

    op.create_table(
        "portfolio_position",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("portfolio_account.id"), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="STOCK"),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False, server_default="0"),
        sa.Column("average_cost", sa.Numeric(28, 8), nullable=False, server_default="0"),
        sa.Column("trade_engine_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_portfolio_position_market"),
        sa.CheckConstraint("asset_type IN ('STOCK','ETF')", name="ck_portfolio_position_asset"),
        sa.CheckConstraint("quantity >= 0", name="ck_portfolio_position_qty"),
    )
    op.create_index("ix_portfolio_position_uid", "portfolio_position", ["uid"])
    op.create_index("ix_portfolio_position_account_id", "portfolio_position", ["account_id"])
    op.create_index(
        "uix_portfolio_position_open_symbol",
        "portfolio_position",
        ["account_id", "symbol"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),  # pragma: allowlist secret
    )

    op.create_table(
        "position_lot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("portfolio_position.id"), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("entry_price", sa.Numeric(28, 8), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('CORE','ADDON')", name="ck_position_lot_role"),
        sa.CheckConstraint("remaining_quantity >= 0", name="ck_position_lot_remaining"),
    )
    op.create_index("ix_position_lot_position_id", "position_lot", ["position_id"])

    op.create_table(
        "trade_operation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("portfolio_account.id"), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("portfolio_position.id"), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("price", sa.Numeric(28, 8), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_trade_operation_side"),
        sa.CheckConstraint("quantity > 0", name="ck_trade_operation_qty"),
        sa.CheckConstraint("price > 0", name="ck_trade_operation_price"),
    )
    op.create_index("ix_trade_operation_uid", "trade_operation", ["uid"])
    op.create_index("ix_trade_operation_account_id", "trade_operation", ["account_id"])
    op.create_index("ix_trade_operation_position_id", "trade_operation", ["position_id"])

    op.create_table(
        "cash_operation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("portfolio_account.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(28, 8), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("type IN ('DEPOSIT','WITHDRAW')", name="ck_cash_operation_type"),
        sa.CheckConstraint("amount > 0", name="ck_cash_operation_amount"),
    )
    op.create_index("ix_cash_operation_uid", "cash_operation", ["uid"])
    op.create_index("ix_cash_operation_account_id", "cash_operation", ["account_id"])

    op.create_table(
        "trade_llm_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_decision", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_trade_llm_state_market"),
        sa.UniqueConstraint("uid", "market", name="uix_trade_llm_state_uid_market"),
    )
    op.create_index("ix_trade_llm_state_uid", "trade_llm_state", ["uid"])

    op.create_table(
        "trade_signal",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("position_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("strategy_key", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("suggested_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("suggested_target_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("llm_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by_llm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("signal_key", sa.String(length=190), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('BUY','ADD','REDUCE','EXIT')", name="ck_trade_signal_action"),
        sa.UniqueConstraint("uid", "signal_key", name="uix_trade_signal_uid_key"),
    )
    op.create_index("ix_trade_signal_uid", "trade_signal", ["uid"])


def downgrade():
    op.drop_table("trade_signal")
    op.drop_table("trade_llm_state")
    op.drop_table("cash_operation")
    op.drop_table("trade_operation")
    op.drop_table("position_lot")
    op.drop_table("portfolio_position")
    op.drop_table("portfolio_account")
