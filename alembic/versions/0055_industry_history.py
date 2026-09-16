"""Allow index-only history without inventing a constituent observation time."""
from alembic import op
import sqlalchemy as sa

revision = "0055_industry_history"
down_revision = "0054_industry_strength"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("industry_strength_snapshot") as batch:
        batch.alter_column("members_observed_at", existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade():
    # Refuse to fabricate observation times or silently discard historical results.
    with op.batch_alter_table("industry_strength_snapshot") as batch:
        batch.alter_column("members_observed_at", existing_type=sa.DateTime(timezone=True), nullable=False)
