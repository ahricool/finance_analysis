"""Allow eight evidence families, preserving all historical V1 snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "0079_confluence_v2"
down_revision = "0078_research_preview"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("confluence_snapshot") as batch:
        batch.drop_constraint("ck_confluence_counts", type_="check")
        batch.create_check_constraint(
            "ck_confluence_counts",
            "positive_signal_count <= available_signal_count AND available_signal_count BETWEEN 0 AND 8",
        )


def downgrade():
    # Do not silently delete V2 evidence to fit the old schema.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM confluence_snapshot WHERE available_signal_count > 5")):
        raise RuntimeError("V2 snapshots with >5 families exist; cannot safely downgrade")
    with op.batch_alter_table("confluence_snapshot") as batch:
        batch.drop_constraint("ck_confluence_counts", type_="check")
        batch.create_check_constraint(
            "ck_confluence_counts",
            "positive_signal_count <= available_signal_count AND available_signal_count BETWEEN 0 AND 5",
        )
