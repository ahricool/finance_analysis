"""Store normalized avatars independently in PostgreSQL BYTEA."""

import logging
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0071_user_avatar"
down_revision = "0070_options_intelligence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_avatar",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    import_legacy_avatars(op.get_bind())


def import_legacy_avatars(connection):
    """Idempotent import, also callable when a previously absent volume is restored."""
    # Old avatars are local files. Import available files, without removing originals.
    from finance_analysis.core.paths import get_avatar_upload_dir
    from finance_analysis.core.time import utc_now
    from finance_analysis.users.avatar import MAX_AVATAR_BYTES, InvalidAvatar, normalize_avatar

    users = sa.table("users", sa.column("id", sa.Integer()), sa.column("avatar_url", sa.String()))
    avatars = sa.table(
        "user_avatar",
        sa.column("user_id", sa.Integer()),
        sa.column("data", sa.LargeBinary()),
        sa.column("version", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    statement = (
        sa.select(users.c.id, users.c.avatar_url)
        .where(users.c.avatar_url.like("/api/v1/auth/avatar/%.jpg%"))
        .with_for_update()
    )
    for uid, url in connection.execute(statement).all():
        if not url or url.split("?", 1)[0] != f"/api/v1/auth/avatar/{uid}.jpg":
            continue
        path = get_avatar_upload_dir() / f"{uid}.jpg"
        try:
            with path.open("rb") as source:
                data = normalize_avatar(source.read(MAX_AVATAR_BYTES + 1), "image/jpeg")
        except (OSError, InvalidAvatar):
            # Do not erase references when the data volume is absent; operators can rerun the import.
            logging.getLogger(__name__).warning("Legacy avatar unavailable for user_id=%s", uid)
            continue
        version = uuid4().hex
        connection.execute(avatars.insert().values(user_id=uid, data=data, version=version, updated_at=utc_now()))
        connection.execute(
            users.update().where(users.c.id == uid).values(avatar_url=f"/api/v1/auth/avatar/{uid}.webp?v={version}")
        )


def downgrade():
    # The old server cannot read DB-only avatars; never retain broken WebP URLs after downgrade.
    op.execute("UPDATE users SET avatar_url = NULL WHERE avatar_url LIKE '/api/v1/auth/avatar/%.webp?v=%'")
    op.drop_table("user_avatar")
