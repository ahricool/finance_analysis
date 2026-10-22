"""Versioned shared stock strategy simulations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0076_stock_strategies"
down_revision = "0075_watch_list_tags"
branch_labels = None
depends_on = None


def upgrade():
    json_type = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
    identity = lambda: [
        sa.Column("strategy_key", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(16), primary_key=True),
        sa.Column("market", sa.String(8), primary_key=True),
    ]
    op.create_table(
        "stock_strategy_launch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("launch_date", sa.Date(), nullable=False),
        sa.Column("universes", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_stock_strategy_launch_singleton"),
    )
    op.create_table(
        "stock_strategy_state",
        *identity(),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("last_date", sa.Date()),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_stock_strategy_state_market"),
    )
    op.create_table(
        "stock_strategy_day",
        *identity(),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=False),
        sa.Column("total_return", sa.Float(), nullable=False),
        sa.Column("cagr", sa.Float()),
        sa.Column("benchmark_return", sa.Float()),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.Column("exposure", sa.Float(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_stock_strategy_day_market"),
        sa.CheckConstraint("nav > 0", name="ck_stock_strategy_day_nav"),
    )
    op.create_table(
        "stock_strategy_run",
        *identity(),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('success', 'waiting', 'failed')", name="ck_stock_strategy_run_status"),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_stock_strategy_run_market"),
    )


def downgrade():
    for table in ("stock_strategy_run", "stock_strategy_day", "stock_strategy_state", "stock_strategy_launch"):
        op.drop_table(table)
