# -*- coding: utf-8 -*-
"""Baseline: create all tables from current SQLAlchemy metadata.

The system has not launched yet, so Alembic is intentionally collapsed to a
single initial revision. Any pre-launch schema adjustment should update the ORM
metadata and this baseline instead of adding stepwise revisions.

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
    # Local import so env.py / CLI can load revision without pulling all ORM at collection time.
    from src.db.base import Base
    import src.models  # noqa: F401  # register ORM models on Base.metadata

    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise NotImplementedError("Baseline schema downgrade is not supported.")
