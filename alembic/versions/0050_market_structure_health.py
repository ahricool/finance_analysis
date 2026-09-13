"""Add closing structure and nullable trend health; never rewrite historical strategy results."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0050_market_structure_health"
down_revision = "0049_notification_center"
branch_labels = None
depends_on = None


def upgrade():
    json_type = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "market_structure_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("benchmark_return_5d", sa.Float()),
        sa.Column("median_member_return_5d", sa.Float()),
        sa.Column("breadth_divergence_5d", sa.Float()),
        sa.Column("member_positive_ratio_5d", sa.Float()),
        sa.Column("member_above_ma10_ratio", sa.Float()),
        sa.Column("member_above_ma20_ratio", sa.Float()),
        sa.Column("rotation_velocity_1d", sa.Float()),
        sa.Column("rotation_velocity_3d", sa.Float()),
        sa.Column("rotation_velocity_5d", sa.Float()),
        sa.Column("leadership_concentration_1d", sa.Float()),
        sa.Column("leadership_concentration_5d", sa.Float()),
        sa.Column("leadership_hhi_5d", sa.Float()),
        sa.Column("metrics_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market", "trade_date", name="uix_market_structure_market_date"),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_market_structure_market"),
    )
    op.add_column("trend_following_snapshot", sa.Column("trend_lifecycle", sa.String(16)))
    op.add_column("trend_following_snapshot", sa.Column("fragility_score", sa.Float()))
    op.add_column("trend_following_snapshot", sa.Column("fragility_breakdown", json_type))


def downgrade():
    op.drop_column("trend_following_snapshot", "fragility_breakdown")
    op.drop_column("trend_following_snapshot", "fragility_score")
    op.drop_column("trend_following_snapshot", "trend_lifecycle")
    op.drop_table("market_structure_snapshot")
