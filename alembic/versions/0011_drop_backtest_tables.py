"""Drop removed backtest tables.

Revision ID: 0011_drop_backtest_tables
Revises: 0010_holdings_decimal_cost
Create Date: 2026-06-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "0011_drop_backtest_tables"
down_revision: Union[str, Sequence[str], None] = "0010_holdings_decimal_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES_IN_DROP_ORDER = (
    "backtest_summaries",
    "backtest_results",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(inspect(bind).get_table_names())
    for table_name in TABLES_IN_DROP_ORDER:
        if table_name in existing_tables:
            op.drop_table(table_name)


def downgrade() -> None:
    raise NotImplementedError("Backtest tables were removed and are not recreated on downgrade.")
