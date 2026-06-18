"""Drop removed portfolio tables.

Revision ID: 0005_drop_portfolio_tables
Revises: 0004_add_finance_events
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "0005_drop_portfolio_tables"
down_revision: Union[str, Sequence[str], None] = "0004_add_finance_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES_IN_DROP_ORDER = (
    "portfolio_position_lots",
    "portfolio_positions",
    "portfolio_daily_snapshots",
    "portfolio_trades",
    "portfolio_cash_ledger",
    "portfolio_corporate_actions",
    "portfolio_fx_rates",
    "portfolio_accounts",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(inspect(bind).get_table_names())
    for table_name in TABLES_IN_DROP_ORDER:
        if table_name in existing_tables:
            op.drop_table(table_name)


def downgrade() -> None:
    raise NotImplementedError("Portfolio tables were removed and are not recreated on downgrade.")
