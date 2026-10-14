"""Persist the weekly industry catalog and current stock membership."""

from alembic import op
import sqlalchemy as sa

revision = "0074_industry_reference"
down_revision = "0073_intraday_confirmation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "industry_catalog",
        sa.Column("industry_code", sa.String(32), primary_key=True),
        sa.Column("industry_name", sa.String(128), nullable=False),
        sa.Column("members_observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "industry_membership",
        sa.Column("industry_code", sa.String(32),
                  sa.ForeignKey("industry_catalog.industry_code", ondelete="CASCADE"), primary_key=True),
        sa.Column("stock_code", sa.String(32), primary_key=True),
        sa.Column("stock_name", sa.String(128), nullable=False),
    )
    op.create_index("ix_industry_membership_stock_code", "industry_membership", ["stock_code"])


def downgrade():
    op.drop_table("industry_membership")
    op.drop_table("industry_catalog")
