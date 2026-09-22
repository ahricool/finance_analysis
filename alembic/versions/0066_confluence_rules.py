"""Persist generation-specific confluence rules; legacy runs remain nullable."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0066_confluence_rules"
down_revision = "0065_confluence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("confluence_run", sa.Column("rules", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=True))


def downgrade():
    op.drop_column("confluence_run", "rules")
