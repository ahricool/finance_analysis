"""Store forward-adjusted daily prices and remove adjustment-factor indirection.

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
    if {"stock_daily", "stock_adjustment_factor"}.issubset(tables):
        factor = """
            SELECT forward_adjustment_factor
            FROM stock_adjustment_factor
            WHERE stock_adjustment_factor.symbol_id = stock_daily.symbol_id
              AND stock_adjustment_factor.trade_date = stock_daily.date
              AND stock_adjustment_factor.forward_adjustment_factor > 0
        """
        op.execute(
            sa.text(
                f"""
                UPDATE stock_daily
                SET open = open * ({factor}),
                    high = high * ({factor}),
                    low = low * ({factor}),
                    close = close * ({factor}),
                    vwap = CASE WHEN vwap IS NULL THEN NULL ELSE vwap * ({factor}) END
                WHERE EXISTS ({factor})
                """
            )
        )
        # Rows without a trustworthy factor cannot remain because they would retain
        # the old raw-price semantics alongside adjusted rows. A subsequent full sync
        # repopulates them directly from adjusted providers.
        op.execute(sa.text(f"DELETE FROM stock_daily WHERE NOT EXISTS ({factor})"))
        op.drop_table("stock_adjustment_factor")

    if "quant_dataset_snapshot" in tables and "price_mode" in _columns("quant_dataset_snapshot"):
        if "ck_quant_dataset_price_mode" in _checks("quant_dataset_snapshot"):
            op.drop_constraint("ck_quant_dataset_price_mode", "quant_dataset_snapshot", type_="check")
        op.drop_column("quant_dataset_snapshot", "price_mode")

    if "backtest_run" in tables and "price_mode" in _columns("backtest_run"):
        op.drop_column("backtest_run", "price_mode")


def downgrade() -> None:
    raise RuntimeError(
        "Migration 0037_forward_adjusted_daily is irreversible: upgrade rewrites daily prices "
        "and deletes legacy adjustment-factor data. Restore a database backup to downgrade."
    )
