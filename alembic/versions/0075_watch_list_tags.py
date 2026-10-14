"""User-owned watch-list labels and many-to-many associations."""

from alembic import op
import sqlalchemy as sa

revision = "0075_watch_list_tags"
down_revision = "0074_industry_reference"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "watch_list_tag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("name_key", sa.String(96), nullable=False),
        sa.UniqueConstraint("uid", "name_key", name="uix_watch_list_tag_uid_name_key"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 32", name="ck_watch_list_tag_name_length"),
    )
    op.create_index("ix_watch_list_tag_uid", "watch_list_tag", ["uid"])
    op.create_table(
        "watch_list_tag_link",
        sa.Column("watch_list_id", sa.Integer(), sa.ForeignKey("watch_list.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("watch_list_tag.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_watch_list_tag_link_tag_id", "watch_list_tag_link", ["tag_id"])


def downgrade():
    op.drop_table("watch_list_tag_link")
    op.drop_table("watch_list_tag")
