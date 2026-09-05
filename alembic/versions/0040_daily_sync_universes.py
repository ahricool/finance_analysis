"""Add supported index and daily synchronization universes.

Revision ID: 0040_daily_sync_universes
Revises: 0039_unified_security
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_daily_sync_universes"
down_revision: Union[str, Sequence[str], None] = "0039_unified_security"
branch_labels = None
depends_on = None

UNIVERSES = (
    ("us_nasdaq100", "Nasdaq 100", "US", "INDEX"),
    ("cn_daily_sync", "A股日线同步", "CN", "STRATEGY"),
    ("us_daily_sync", "美股日线同步", "US", "STRATEGY"),
)

INCLUDES = (
    ("cn_daily_sync", "cn_csi300"),
    ("cn_daily_sync", "cn_csi500"),
    ("cn_daily_sync", "cn_csi1000"),
    ("us_daily_sync", "us_sp500"),
)


def upgrade() -> None:
    connection = op.get_bind()
    for key, name, market, universe_type in UNIVERSES:
        connection.execute(
            sa.text("""
                INSERT INTO universe (key, name, market, universe_type, enabled, config, created_at, updated_at)
                VALUES (:key, :name, :market, :universe_type, true, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET
                    name = EXCLUDED.name,
                    market = EXCLUDED.market,
                    universe_type = EXCLUDED.universe_type,
                    enabled = true
            """),
            {"key": key, "name": name, "market": market, "universe_type": universe_type},
        )
    for parent, child in INCLUDES:
        connection.execute(
            sa.text("""
                INSERT INTO universe_include (universe_id, included_universe_id, created_at)
                SELECT parent.id, child.id, CURRENT_TIMESTAMP
                FROM universe parent, universe child
                WHERE parent.key = :parent AND child.key = :child
                ON CONFLICT (universe_id, included_universe_id) DO NOTHING
            """),
            {"parent": parent, "child": child},
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("""
        DELETE FROM universe_include
        WHERE universe_id IN (SELECT id FROM universe WHERE key IN ('cn_daily_sync', 'us_daily_sync'))
    """))
    connection.execute(sa.text("""
        DELETE FROM universe WHERE key IN ('us_nasdaq100', 'cn_daily_sync', 'us_daily_sync')
    """))
