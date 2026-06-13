"""Harden users.extra as jsonb profile extension data.

Revision ID: 0002_users_extra_jsonb
Revises: 0001_baseline
Create Date: 2026-06-12
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_users_extra_jsonb"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'extra'
            ) THEN
                ALTER TABLE users ALTER COLUMN extra DROP DEFAULT;
                ALTER TABLE users
                ALTER COLUMN extra TYPE jsonb
                USING COALESCE(extra::jsonb, '{}'::jsonb);
            ELSE
                ALTER TABLE users ADD COLUMN extra jsonb;
            END IF;
        END $$;
        """
    )
    op.execute("UPDATE users SET extra = '{}'::jsonb WHERE extra IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN extra SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE users ALTER COLUMN extra SET NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_extra ON users USING GIN (extra)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_extra")
    op.execute("ALTER TABLE users ALTER COLUMN extra DROP NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN extra DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN extra TYPE json USING extra::json")
