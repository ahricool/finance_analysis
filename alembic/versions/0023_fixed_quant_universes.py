"""Rename Quant universes and mark them as fixed index definitions.

Revision ID: 0023_fixed_quant_universes
Revises: 0022_forward_adjustment_naming
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_fixed_quant_universes"
down_revision: Union[str, Sequence[str], None] = "0022_forward_adjustment_naming"
branch_labels = None
depends_on = None


_UNIVERSES = (
    {
        "market": "US",
        "old_key": "us_sp500_watchlist",
        "key": "us_sp500",
        "name": "S&P 500",
        "description": "Fixed S&P 500 constituents from SP500_STOCK_INDEX.",
        "benchmark_code": "QQQ.US",
        "constituent_source": "SP500_STOCK_INDEX",
    },
    {
        "market": "CN",
        "old_key": "cn_csi300_watchlist",
        "key": "cn_csi300",
        "name": "沪深300",
        "description": "Fixed CSI 300 constituents from CSI300_STOCK_INDEX.",
        "benchmark_code": "510300.SH",
        "constituent_source": "CSI300_STOCK_INDEX",
    },
)


def upgrade() -> None:
    connection = op.get_bind()
    for item in _UNIVERSES:
        existing_target = connection.scalar(
            sa.text("SELECT id FROM quant_universe WHERE key = :key"),
            {"key": item["key"]},
        )
        existing_source = connection.scalar(
            sa.text("SELECT id FROM quant_universe WHERE key = :key"),
            {"key": item["old_key"]},
        )
        if existing_source is not None and existing_target is not None:
            raise RuntimeError(
                f"Cannot preserve Quant Universe id: both {item['old_key']} and {item['key']} exist"
            )

        source_key = item["old_key"] if existing_source is not None else item["key"]
        connection.execute(
            sa.text(
                """
                UPDATE quant_universe
                SET key = :key,
                    name = :name,
                    market = :market,
                    description = :description,
                    enabled = true,
                    is_dynamic = false,
                    benchmark_code = :benchmark_code,
                    sector_benchmark_mode = 'market_dependencies',
                    config = jsonb_build_object('constituent_source', :constituent_source),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = :source_key
                """
            ),
            {
                **item,
                "source_key": source_key,
            },
        )

    # This row may still be referenced by historical artifacts. Keep it for
    # referential integrity, but make it unavailable to all current workflows.
    connection.execute(
        sa.text(
            """
            UPDATE quant_universe
            SET enabled = false,
                is_dynamic = false,
                config = jsonb_build_object('supported', false),
                updated_at = CURRENT_TIMESTAMP
            WHERE key = :unsupported_key
            """
        ),
        {"unsupported_key": "us_ai_semiconductor"},
    )


def downgrade() -> None:
    connection = op.get_bind()
    for item in _UNIVERSES:
        connection.execute(
            sa.text(
                """
                UPDATE quant_universe
                SET key = :old_key,
                    name = :name,
                    description = :description,
                    is_dynamic = true,
                    config = jsonb_build_object('scope_resolver', 'MarketDataScopeResolver'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = :key
                """
            ),
            {
                "key": item["key"],
                "old_key": item["old_key"],
                "name": (
                    "S&P 500 + US watchlist"
                    if item["market"] == "US"
                    else "沪深300 + A股自选"
                ),
                "description": (
                    "Dynamic mirror of the shared US daily synchronization scope."
                    if item["market"] == "US"
                    else "Dynamic mirror of the shared CN daily synchronization scope."
                ),
            },
        )
