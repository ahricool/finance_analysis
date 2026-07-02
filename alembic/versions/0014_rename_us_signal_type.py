"""Rename the US intraday strong-to-weak signal type.

Revision ID: 0014_rename_us_signal_type
Revises: 0013_signal_metadata
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0014_rename_us_signal_type"
down_revision: Union[str, Sequence[str], None] = "0013_signal_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE signal SET signal_type = 'strong_to_weak_failure' " "WHERE signal_type = 'relative_strength_failure'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE signal SET signal_type = 'relative_strength_failure' " "WHERE signal_type = 'strong_to_weak_failure'"
    )
