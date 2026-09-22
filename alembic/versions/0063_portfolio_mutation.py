"""Transactional portfolio mutation receipts.

Revision ID: 0063_portfolio_mutation
Revises: 0062_holdings_portfolio_risk
"""
from alembic import op
import sqlalchemy as sa

revision = "0063_portfolio_mutation"
down_revision = "0062_holdings_portfolio_risk"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portfolio_mutation",
        sa.Column("uid", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("portfolio_mutation")
