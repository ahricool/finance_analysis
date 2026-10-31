"""Cancel unfinished jobs belonging to retired stock decision analysis.

Historical reports, snapshots and completed task records remain untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "0083_retire_stock_analysis"
down_revision = "0082_intraday_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    tasks = sa.table(
        "task",
        sa.column("task_type", sa.String),
        sa.column("scheduler_job_id", sa.String),
        sa.column("status", sa.String),
        sa.column("message", sa.String),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        tasks.update()
        .where(
            tasks.c.status.in_(("pending", "processing", "retrying")),
            sa.or_(
                tasks.c.task_type.in_(("stock_analysis", "scheduled_us_premarket")),
                tasks.c.scheduler_job_id == "analysis_us_premarket",
            ),
        )
        .values(
            status="cancelled",
            message="个股决策分析功能已移除，未完成任务已取消",
            finished_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )


def downgrade():
    # A downgrade cannot safely resubmit or resume retired work.
    pass
