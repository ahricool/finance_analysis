"""Reset daily storage for provider-adjusted prices and remove legacy indirection.

Revision ID: 0037_forward_adjusted_daily
Revises: 0036_unified_task_mutex
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_forward_adjusted_daily"
down_revision: Union[str, Sequence[str], None] = "0036_unified_task_mutex"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _checks(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    tables = _tables()
    if "market_data_symbol" in tables:
        if "ck_market_data_symbol_lot_size" in _checks("market_data_symbol"):
            op.drop_constraint("ck_market_data_symbol_lot_size", "market_data_symbol", type_="check")
        if "lot_size" in _columns("market_data_symbol"):
            op.drop_column("market_data_symbol", "lot_size")

    if "stock_daily" in tables:
        # Legacy rows have raw-price provenance and must not be relabelled by applying
        # locally stored factors. The next full sync rebuilds them from provider APIs.
        op.execute(sa.text("DELETE FROM stock_daily"))

    if "stock_adjustment_factor" in tables:
        op.drop_table("stock_adjustment_factor")

    if "stock_corporate_action" in tables:
        op.drop_table("stock_corporate_action")

    if "stock_daily" in tables:
        checks = _checks("stock_daily")
        for constraint in ("ck_stock_daily_vwap_quality", "ck_stock_daily_vwap_positive"):
            if constraint in checks:
                op.drop_constraint(constraint, "stock_daily", type_="check")
        columns = _columns("stock_daily")
        for column in ("limit_up", "limit_down", "suspended", "vwap", "vwap_source", "vwap_quality"):
            if column in columns:
                op.drop_column("stock_daily", column)

    for table_name in ("backtest_trade", "backtest_equity", "backtest_run"):
        if table_name in tables:
            op.drop_table(table_name)

    if "quant_dataset_snapshot" in tables and "price_mode" in _columns("quant_dataset_snapshot"):
        if "ck_quant_dataset_price_mode" in _checks("quant_dataset_snapshot"):
            op.drop_constraint("ck_quant_dataset_price_mode", "quant_dataset_snapshot", type_="check")
        op.drop_column("quant_dataset_snapshot", "price_mode")


def downgrade() -> None:
    raise RuntimeError(
        "Migration 0037_forward_adjusted_daily is irreversible: upgrade deletes legacy daily prices "
        "and adjustment storage. Restore a database backup to downgrade."
    )
