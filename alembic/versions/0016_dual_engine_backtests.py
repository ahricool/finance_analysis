"""Add engine-neutral daily backtest result tables.

Revision ID: 0016_dual_engine_backtests
Revises: 0015_market_data_history
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_dual_engine_backtests"
down_revision: Union[str, Sequence[str], None] = "0015_market_data_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    symbol_columns = {item["name"] for item in inspector.get_columns("market_data_symbol")}
    daily_columns = {item["name"] for item in inspector.get_columns("stock_daily")}
    if "lot_size" not in symbol_columns:
        op.add_column("market_data_symbol", sa.Column("lot_size", sa.Integer(), nullable=True))
    symbol_checks = {item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints("market_data_symbol")}
    if "ck_market_data_symbol_lot_size" not in symbol_checks:
        op.create_check_constraint(
            "ck_market_data_symbol_lot_size", "market_data_symbol", "lot_size IS NULL OR lot_size > 0"
        )
    if "limit_up" not in daily_columns:
        op.add_column("stock_daily", sa.Column("limit_up", sa.Float(), nullable=True))
    if "limit_down" not in daily_columns:
        op.add_column("stock_daily", sa.Column("limit_down", sa.Float(), nullable=True))
    if "suspended" not in daily_columns:
        op.add_column(
            "stock_daily", sa.Column("suspended", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    if "backtest_run" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "backtest_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("engine", sa.String(length=24), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("engine_config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("strategy_key", sa.String(length=64), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("initial_cash", sa.Float(), nullable=False),
        sa.Column("benchmark_code", sa.String(length=32), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("price_mode", sa.String(length=16), server_default="raw", nullable=False),
        sa.Column("market_rule_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("engine IN ('backtrader', 'rqalpha')", name="ck_backtest_run_engine"),
        sa.CheckConstraint(
            "status IN ('pending','processing','completed','failed','cancelled')",
            name="ck_backtest_run_status",
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_backtest_run_progress"),
        sa.CheckConstraint("end_date >= start_date", name="ck_backtest_run_dates"),
        sa.CheckConstraint("initial_cash > 0", name="ck_backtest_run_initial_cash"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uix_backtest_run_task_id"),
    )
    op.create_index("ix_backtest_run_uid_created_at", "backtest_run", ["uid", "created_at"])
    op.create_index("ix_backtest_run_engine_created_at", "backtest_run", ["engine", "created_at"])
    op.create_index("ix_backtest_run_strategy_created_at", "backtest_run", ["strategy_key", "created_at"])
    op.create_index("ix_backtest_run_status_created_at", "backtest_run", ["status", "created_at"])

    op.create_table(
        "backtest_trade",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("engine_order_id", sa.String(length=128), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("gross_amount", sa.Float(), nullable=False),
        sa.Column("commission", sa.Float(), server_default="0", nullable=False),
        sa.Column("tax", sa.Float(), server_default="0", nullable=False),
        sa.Column("other_fee", sa.Float(), server_default="0", nullable=False),
        sa.Column("total_fee", sa.Float(), server_default="0", nullable=False),
        sa.Column("cash_after", sa.Float(), nullable=False),
        sa.Column("position_after", sa.Float(), nullable=False),
        sa.Column("return_pct", sa.Float(), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_backtest_trade_side"),
        sa.CheckConstraint("quantity > 0", name="ck_backtest_trade_quantity"),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_trade_run_date", "backtest_trade", ["run_id", "trade_date"])
    op.create_index("ix_backtest_trade_run_code", "backtest_trade", ["run_id", "code"])

    op.create_table(
        "backtest_equity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("position_value", sa.Float(), nullable=False),
        sa.Column("total_equity", sa.Float(), nullable=False),
        sa.Column("benchmark_equity", sa.Float(), nullable=True),
        sa.Column("daily_return_pct", sa.Float(), nullable=False),
        sa.Column("cumulative_return_pct", sa.Float(), nullable=False),
        sa.Column("benchmark_return_pct", sa.Float(), nullable=True),
        sa.Column("drawdown_pct", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "trading_date", name="uix_backtest_equity_run_date"),
    )
    op.create_index("ix_backtest_equity_run_date", "backtest_equity", ["run_id", "trading_date"])


def downgrade() -> None:
    op.drop_index("ix_backtest_equity_run_date", table_name="backtest_equity")
    op.drop_table("backtest_equity")
    op.drop_index("ix_backtest_trade_run_code", table_name="backtest_trade")
    op.drop_index("ix_backtest_trade_run_date", table_name="backtest_trade")
    op.drop_table("backtest_trade")
    op.drop_index("ix_backtest_run_status_created_at", table_name="backtest_run")
    op.drop_index("ix_backtest_run_strategy_created_at", table_name="backtest_run")
    op.drop_index("ix_backtest_run_engine_created_at", table_name="backtest_run")
    op.drop_index("ix_backtest_run_uid_created_at", table_name="backtest_run")
    op.drop_table("backtest_run")
    op.drop_column("stock_daily", "suspended")
    op.drop_column("stock_daily", "limit_down")
    op.drop_column("stock_daily", "limit_up")
    op.drop_constraint("ck_market_data_symbol_lot_size", "market_data_symbol", type_="check")
    op.drop_column("market_data_symbol", "lot_size")
