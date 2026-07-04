"""Add versioned quantitative research storage.

Revision ID: 0017_quant_research
Revises: 0016_dual_engine_backtests
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from finance_analysis.database.models.quant import QUANT_TABLES

revision: str = "0017_quant_research"
down_revision: Union[str, Sequence[str], None] = "0016_dual_engine_backtests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for model in QUANT_TABLES:
        model.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(QUANT_TABLES):
        model.__table__.drop(bind, checkfirst=True)
