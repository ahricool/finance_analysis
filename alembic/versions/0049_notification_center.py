"""Separate durable messages from timeline reports and calendar delivery state.

Revision ID: 0049_notification_center
Revises: 0048_trend_duration_days
"""

from alembic import op
import sqlalchemy as sa

revision = "0049_notification_center"
down_revision = "0048_trend_duration_days"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("route_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for prefix in ([], ["uid"], ["route_type"], ["severity"]):
        columns = prefix + ["created_at"]
        op.create_index("ix_notification_" + "_".join(columns), "notification", columns)
    op.execute(sa.text("DELETE FROM timeline_entries"))
    with op.batch_alter_table("finance_events") as batch:
        batch.drop_column("notified_at")
        batch.drop_column("notification_fingerprint")


def downgrade():
    raise RuntimeError("Notification history cleanup is irreversible")
