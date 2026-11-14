"""Remove the prediction catalog and its retired sync task history."""

from alembic import op
import sqlalchemy as sa

revision = "0092_retire_prediction_catalog"
down_revision = "0091_prediction_markets"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("prediction_event")
    op.drop_table("prediction_tag")
    tasks = sa.table("task", sa.column("task_type"), sa.column("scheduler_job_id"))
    op.execute(
        tasks.delete().where(
            sa.or_(
                tasks.c.task_type == "scheduled_polymarket_catalog_sync",
                tasks.c.scheduler_job_id == "polymarket_catalog_sync",
            )
        )
    )


def downgrade():
    raise RuntimeError("Retired prediction catalog deletion is irreversible")
