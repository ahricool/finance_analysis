"""Strengthen market isolation for dual-market quantitative research.

Revision ID: 0020_quant_dual_market
Revises: 0019_stock_daily_vwap
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_quant_dual_market"
down_revision: Union[str, Sequence[str], None] = "0019_stock_daily_vwap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    signal_constraints = {item["name"] for item in inspector.get_unique_constraints("model_signal")}
    if "uix_model_signal" in signal_constraints:
        op.drop_constraint("uix_model_signal", "model_signal", type_="unique")
    signal_constraints = {
        item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("model_signal")
    }
    if "uix_model_signal_market_universe" not in signal_constraints:
        op.create_unique_constraint(
            "uix_model_signal_market_universe",
            "model_signal",
            ["market", "universe_id", "trade_date", "symbol_id", "model_version"],
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("model_run")}
    if "uix_model_run_production_market_key" not in indexes:
        # Older deployments may already contain more than one production run.
        # Keep the newest production artifact and retire the others before
        # enforcing the per-market invariant.
        op.execute(
            sa.text(
                """
                WITH ranked AS (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY market, model_key
                               ORDER BY finished_at DESC NULLS LAST, id DESC
                           ) AS position
                    FROM model_run
                    WHERE status = 'production'
                )
                UPDATE model_run
                SET status = 'retired'
                FROM ranked
                WHERE model_run.id = ranked.id AND ranked.position > 1
                """
            )
        )
        op.create_index(
            "uix_model_run_production_market_key",
            "model_run",
            ["market", "model_key"],
            unique=True,
            postgresql_where=sa.text("status = 'production'"),
        )


def downgrade() -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("model_run")}
    if "uix_model_run_production_market_key" in indexes:
        op.drop_index("uix_model_run_production_market_key", table_name="model_run")
    constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("model_signal")}
    if "uix_model_signal_market_universe" in constraints:
        op.drop_constraint("uix_model_signal_market_universe", "model_signal", type_="unique")
    op.create_unique_constraint(
        "uix_model_signal",
        "model_signal",
        ["trade_date", "symbol_id", "model_version"],
    )
