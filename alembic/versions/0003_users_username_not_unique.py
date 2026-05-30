# -*- coding: utf-8 -*-
"""Allow duplicate usernames; keep email as the login identifier.

Revision ID: 0003_users_username_not_unique
Revises: 0002_watch_list_is_favorite
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_users_username_not_unique"
down_revision: Union[str, Sequence[str], None] = "0002_watch_list_is_favorite"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.create_index("ix_users_username", "users", ["username"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.create_index("ix_users_username", "users", ["username"], unique=True)
