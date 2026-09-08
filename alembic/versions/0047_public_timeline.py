"""Turn the investment timeline into a public market board.

Revision ID: 0047_public_timeline
Revises: 0046_simplify_quant

Manual notes were the only user-owned timeline content, so they are deleted and the
owner column is dropped. Public market reports (pre-close, premarket, postmarket)
are kept untouched.
"""

from sqlalchemy import inspect, text

from alembic import op

revision = "0047_public_timeline"
down_revision = "0046_simplify_quant"
branch_labels = None
depends_on = None

TABLE = "timeline_entries"
PUBLIC_TYPES = ("a_share_pre_close", "us_premarket", "us_postmarket")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    op.execute(text(f"DELETE FROM {TABLE} WHERE entry_type = 'manual_note'"))  # nosec B608
    op.execute(text(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS ck_timeline_type"))
    op.create_check_constraint(
        "ck_timeline_type",
        TABLE,
        "entry_type IN (" + ", ".join(f"'{value}'" for value in PUBLIC_TYPES) + ")",
    )
    if "uid" in {column["name"] for column in inspector.get_columns(TABLE)}:
        op.drop_column(TABLE, "uid")


def downgrade() -> None:
    raise RuntimeError("The public timeline migration deletes notes; restore a backup to roll back.")
