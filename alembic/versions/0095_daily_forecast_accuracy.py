"""Latest next-session check and cumulative daily Kronos errors."""

from alembic import op
import sqlalchemy as sa

revision = "0095_daily_forecast_accuracy"
down_revision = "0094_daily_kronos_forecast"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_forecast_accuracy",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("symbol", sa.String(36), primary_key=True),
        sa.Column("model", sa.String(20), nullable=False),
        sa.Column("weights_revision", sa.String(128), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_close", sa.Float(), nullable=False),
        sa.Column("recent_error", sa.Float(), nullable=False),
        sa.Column("recent_baseline_error", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("error_sum", sa.Float(), nullable=False),
        sa.Column("baseline_error_sum", sa.Float(), nullable=False),
        sa.CheckConstraint("market IN ('CN', 'US')", name="ck_daily_forecast_accuracy_market"),
        sa.CheckConstraint("sample_count > 0", name="ck_daily_forecast_accuracy_count"),
    )


def downgrade():
    op.drop_table("daily_forecast_accuracy")
