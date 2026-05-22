# -*- coding: utf-8 -*-
"""Baseline: create tables from SQLAlchemy metadata (bridge for existing installs).

Existing databases that already match the ORM schema will largely no-op
(``create_all`` skips existing tables) and only record this revision in
``alembic_version``. Subsequent revisions should use autogenerate or hand-written
``op.*`` DDL.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-02-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Local import so env.py / CLI can load revision without pulling all ORM at collection time
    from src.storage import Base

    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise NotImplementedError("Baseline schema downgrade is not supported.")
