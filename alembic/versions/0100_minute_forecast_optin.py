"""Default all minute forecasts to off; persist explicit symbol opt-ins."""

from alembic import op
import sqlalchemy as sa

revision = "0100_minute_forecast_optin"
down_revision = "0099_paper_control"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "minute_forecast_preference",
        sa.Column("symbol", sa.String(32), primary_key=True),
    )


def downgrade():
    op.drop_table("minute_forecast_preference")
