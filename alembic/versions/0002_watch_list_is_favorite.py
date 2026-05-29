# -*- coding: utf-8 -*-
"""Add is_favorite to watch_list for special attention marking.

Revision ID: 0002_watch_list_is_favorite
Revises: 0001_baseline
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_watch_list_is_favorite"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watch_list",
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("watch_list", "is_favorite", server_default=None)


def downgrade() -> None:
    op.drop_column("watch_list", "is_favorite")
