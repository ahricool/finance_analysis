"""Persist last published holdings snapshot for Redis rebuild."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB  # pragma: allowlist secret

revision = "0059_holdings_published_snapshot"
down_revision = "0058_holdings_portfolio_risk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "holding_source",
        sa.Column("published_snapshot", JSONB(), nullable=True),
    )


def downgrade():
    op.drop_column("holding_source", "published_snapshot")
