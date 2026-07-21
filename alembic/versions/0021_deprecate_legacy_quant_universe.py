"""Deprecate the legacy fixed US quantitative universe.

Revision ID: 0021_deprecate_legacy_universe
Revises: 0020_quant_dual_market
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_deprecate_legacy_universe"
down_revision: Union[str, Sequence[str], None] = "0020_quant_dual_market"
branch_labels = None
depends_on = None

_LEGACY_KEY = "us_ai_semiconductor"
_REPLACEMENT_KEY = "us_sp500_watchlist"
_MIGRATION_MARKER = revision


def upgrade() -> None:
    """Keep historical relations intact while blocking all future use."""
    op.execute(
        sa.text(
            """
            UPDATE quant_universe
            SET enabled = false,
                config = COALESCE(config, '{}'::jsonb)
                         || CAST(:deprecation AS jsonb)
                         || jsonb_build_object(
                             'deprecated_previous_enabled',
                             CASE
                                 WHEN COALESCE(config, '{}'::jsonb) ? 'deprecated_previous_enabled'
                                 THEN (config ->> 'deprecated_previous_enabled')::boolean
                                 ELSE enabled
                             END
                         )
            WHERE key = :legacy_key
            """
        ).bindparams(
            legacy_key=_LEGACY_KEY,
            deprecation=(
                '{"deprecated": true, '
                '"deprecated_reason": "Only market-wide SP500/watchlist and CSI300/watchlist universes are supported", '
                f'"replacement_universe": "{_REPLACEMENT_KEY}", '
                f'"deprecated_by_migration": "{_MIGRATION_MARKER}"}}'
            ),
        )
    )
    # A production run bound to the disabled universe would both be unusable
    # and prevent a supported-universe run from being published due to the
    # per-market/model production uniqueness constraint.
    op.execute(
        sa.text(
            """
            UPDATE model_run
            SET status = 'retired'
            WHERE status = 'production'
              AND universe_id = (
                  SELECT id FROM quant_universe WHERE key = :legacy_key
              )
            """
        ).bindparams(legacy_key=_LEGACY_KEY)
    )


def downgrade() -> None:
    """Remove this migration's deprecation marker without deleting history.

    Retired production runs remain retired because automatically republishing
    model artifacts during downgrade would be an unsafe external behavior.
    """
    op.execute(
        sa.text(
            """
            UPDATE quant_universe
            SET enabled = COALESCE(
                    (config ->> 'deprecated_previous_enabled')::boolean,
                    enabled
                ),
                config = COALESCE(config, '{}'::jsonb)
                         - 'deprecated'
                         - 'deprecated_reason'
                         - 'replacement_universe'
                         - 'deprecated_by_migration'
                         - 'deprecated_previous_enabled'
            WHERE key = :legacy_key
              AND config ->> 'deprecated_by_migration' = :marker
            """
        ).bindparams(legacy_key=_LEGACY_KEY, marker=_MIGRATION_MARKER)
    )
