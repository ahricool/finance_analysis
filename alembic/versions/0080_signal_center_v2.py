"""Preserve legacy decisions and add multi-security research and search audit."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0080_signal_center_v2"
down_revision = "0079_confluence_v2"
branch_labels = None
depends_on = None


def upgrade():
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    with op.batch_alter_table("signal_center_run") as batch:
        batch.add_column(sa.Column("recommendations", json_type, nullable=True))
        batch.add_column(sa.Column("search_evidence", json_type, nullable=True))
        batch.add_column(sa.Column("notification_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_signal_center_notification", "notification", ["notification_id"], ["id"], ondelete="SET NULL"
        )
    # NULL recommendations identifies immutable V1 results; no historical backfill/reinterpretation.


def downgrade():
    with op.batch_alter_table("signal_center_run") as batch:
        batch.drop_constraint("fk_signal_center_notification", type_="foreignkey")
        batch.drop_column("notification_id")
        batch.drop_column("search_evidence")
        batch.drop_column("recommendations")
