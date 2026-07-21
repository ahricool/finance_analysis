"""Mark fixed Quant universes as using market benchmark dependencies.

Revision ID: 0024_quant_market_dependencies
Revises: 0023_fixed_quant_universes
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_quant_market_dependencies"
down_revision: Union[str, Sequence[str], None] = "0023_fixed_quant_universes"
branch_labels = None
depends_on = None


_FIXED_UNIVERSE_KEYS = ("us_sp500", "cn_csi300")


def _set_benchmark_mode(value: str) -> None:
    statement = sa.text(
        """
        UPDATE quant_universe
        SET sector_benchmark_mode = :benchmark_mode,
            updated_at = CURRENT_TIMESTAMP
        WHERE key IN :universe_keys
        """
    ).bindparams(sa.bindparam("universe_keys", expanding=True))
    op.get_bind().execute(
        statement,
        {
            "benchmark_mode": value,
            "universe_keys": _FIXED_UNIVERSE_KEYS,
        },
    )


def upgrade() -> None:
    _set_benchmark_mode("market_dependencies")


def downgrade() -> None:
    _set_benchmark_mode("member_or_synthetic")
