"""Shared prediction catalog; never persist prices."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0091_prediction_markets"
down_revision = "0090_trend_ten_day"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prediction_tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("tag_id", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("rule_group", sa.String(32), nullable=False),
        sa.Column("manual_visible", sa.Boolean()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "tag_id", name="uq_prediction_tag_provider"),
    )
    op.create_table(
        "prediction_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tag_ids", JSONB(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("closed", sa.Boolean()),
        sa.Column("archived", sa.Boolean()),
        sa.Column("retained", sa.Boolean(), nullable=False),
        sa.Column("rule_retained", sa.Boolean(), nullable=False),
        sa.Column("rule_reason", sa.String(80), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("manual_retained", sa.Boolean()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_prediction_event_provider"),
    )
    op.create_index("ix_prediction_event_list", "prediction_event", ["retained", "closed", "synced_at"])


def downgrade():
    op.drop_table("prediction_event")
    op.drop_table("prediction_tag")
