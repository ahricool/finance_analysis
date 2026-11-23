"""Latest-only CN and US daily Kronos forecasts."""

from alembic import op
import sqlalchemy as sa

revision = "0094_daily_kronos_forecast"
down_revision = "0093_intraday_simulation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_forecast_snapshot",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("symbol", sa.String(36), primary_key=True),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("anchor_close", sa.Float(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(20), nullable=False),
        sa.Column("weights_revision", sa.String(128), nullable=False),
        sa.Column("lookback", sa.Integer(), nullable=False),
        sa.Column("bars", sa.JSON(), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_daily_forecast_market"),
    )


def downgrade():
    op.drop_table("daily_forecast_snapshot")
