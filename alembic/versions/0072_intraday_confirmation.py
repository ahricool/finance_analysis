"""Persist daily intraday confirmation pools and immutable first-confirmation evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0072_intraday_confirmation"
down_revision = "0071_user_avatar"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intraday_confirmation_snapshot",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("payload", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("returns_pending", sa.Boolean(), nullable=False),
        sa.Column("returns_checked_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('CN','US')", name="ck_intraday_confirmation_market"),
        sa.CheckConstraint("revision > 0", name="ck_intraday_confirmation_revision"),
    )


def downgrade():
    op.drop_table("intraday_confirmation_snapshot")
