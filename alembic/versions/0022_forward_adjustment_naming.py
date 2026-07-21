"""Rename forward-adjustment fields and dataset price mode without losing data.

Revision ID: 0022_forward_adjustment_naming
Revises: 0021_deprecate_legacy_universe
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_forward_adjustment_naming"
down_revision: Union[str, Sequence[str], None] = "0021_deprecate_legacy_universe"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _checks(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    columns = _columns("stock_adjustment_factor")
    if "qfq_factor" in columns and "forward_adjustment_factor" not in columns:
        op.alter_column(
            "stock_adjustment_factor",
            "qfq_factor",
            new_column_name="forward_adjustment_factor",
            existing_type=sa.Float(),
            existing_nullable=True,
        )

    checks = _checks("stock_adjustment_factor")
    if "ck_stock_adjustment_qfq_positive" in checks:
        op.drop_constraint(
            "ck_stock_adjustment_qfq_positive",
            "stock_adjustment_factor",
            type_="check",
        )
    if "ck_stock_adjustment_forward_factor_positive" not in checks:
        op.create_check_constraint(
            "ck_stock_adjustment_forward_factor_positive",
            "stock_adjustment_factor",
            "forward_adjustment_factor IS NULL OR forward_adjustment_factor > 0",
        )

    dataset_checks = _checks("quant_dataset_snapshot")
    if "ck_quant_dataset_price_mode" in dataset_checks:
        op.drop_constraint("ck_quant_dataset_price_mode", "quant_dataset_snapshot", type_="check")
    op.alter_column(
        "quant_dataset_snapshot",
        "price_mode",
        type_=sa.String(length=24),
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default=None,
    )
    op.execute(
        "UPDATE quant_dataset_snapshot SET price_mode = 'forward_adjusted' WHERE price_mode = 'adjusted'"
    )
    op.create_check_constraint(
        "ck_quant_dataset_price_mode",
        "quant_dataset_snapshot",
        "price_mode IN ('raw','forward_adjusted')",
    )


def downgrade() -> None:
    dataset_checks = _checks("quant_dataset_snapshot")
    if "ck_quant_dataset_price_mode" in dataset_checks:
        op.drop_constraint("ck_quant_dataset_price_mode", "quant_dataset_snapshot", type_="check")
    op.execute("UPDATE quant_dataset_snapshot SET price_mode = 'adjusted' WHERE price_mode = 'forward_adjusted'")
    op.alter_column(
        "quant_dataset_snapshot",
        "price_mode",
        type_=sa.String(length=16),
        existing_type=sa.String(length=24),
        existing_nullable=False,
        server_default=None,
    )
    op.create_check_constraint(
        "ck_quant_dataset_price_mode",
        "quant_dataset_snapshot",
        "price_mode IN ('raw','adjusted')",
    )

    checks = _checks("stock_adjustment_factor")
    if "ck_stock_adjustment_forward_factor_positive" in checks:
        op.drop_constraint(
            "ck_stock_adjustment_forward_factor_positive",
            "stock_adjustment_factor",
            type_="check",
        )
    columns = _columns("stock_adjustment_factor")
    if "forward_adjustment_factor" in columns and "qfq_factor" not in columns:
        op.alter_column(
            "stock_adjustment_factor",
            "forward_adjustment_factor",
            new_column_name="qfq_factor",
            existing_type=sa.Float(),
            existing_nullable=True,
        )
    op.create_check_constraint(
        "ck_stock_adjustment_qfq_positive",
        "stock_adjustment_factor",
        "qfq_factor IS NULL OR qfq_factor > 0",
    )
