"""Materialize the latest industry constituents independently of historical snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "0058_industry_constituents"
down_revision = "0057_us_trend_universe"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "industry_strength_constituent",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("industry_code", sa.String(32), nullable=False),
        sa.Column("stock_code", sa.String(32), nullable=False),
        sa.Column("stock_name", sa.String(128), nullable=False),
        sa.Column("price", sa.Float()),
        sa.Column("change_pct", sa.Float()),
        sa.Column("volume", sa.Float()),
        sa.Column("amount", sa.Float()),
        sa.Column("above_ma5", sa.Boolean()),
        sa.Column("above_ma20", sa.Boolean()),
        sa.Column("trend_rank", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("industry_code", "stock_code", name="uix_industry_strength_constituent_code"),
    )


def downgrade():
    op.drop_table("industry_strength_constituent")
