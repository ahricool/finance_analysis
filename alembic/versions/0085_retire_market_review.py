"""Remove old manual market recap history and its identifiable private logs."""

import fcntl
import json
import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0085_retire_market_review"
down_revision = "0084_drop_stock_analysis_archive"
branch_labels = None
depends_on = None


def _purge_files(task_logs):
    from finance_analysis.core.paths import get_log_dir

    root = get_log_dir().resolve()
    paths = []
    for name in task_logs:
        if not name:
            continue
        path = (root / name).resolve()
        if path.is_relative_to(root) and path.is_file():
            paths.append(path)
    for folder in ("celery", "scheduler"):
        for prefix in ("大盘复盘_", "market_review_", "analysis.run_market_review_"):
            for path in (root / folder).glob(prefix + "*.log"):
                if not path.is_symlink():
                    paths.append(path)
    for path in set(paths):
        path.unlink(missing_ok=True)
    audit_dir = Path(os.getenv("LLM_LOG_DIR") or root / "llm")
    for path in audit_dir.glob("*.log"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("r+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            lines = handle.readlines()
            kept = []
            for line in lines:
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    row = None
                if not isinstance(row, dict) or row.get("call_type") != "market_review":
                    kept.append(line)
            if len(kept) != len(lines):
                handle.seek(0)
                handle.writelines(kept)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())


def upgrade():
    tasks = sa.table("task", sa.column("task_type"), sa.column("task_log"), sa.column("result"))
    messages = sa.table(
        "notification", sa.column("id", sa.Integer), sa.column("title"), sa.column("route_type"), sa.column("content")
    )
    usage = sa.table("llm_usage", sa.column("call_type"))
    notification_ids = []
    if op.get_context().as_sql:
        # PostgreSQL 16 validates malformed legacy JSON before parsing it.
        op.execute("""DELETE FROM notification WHERE id IN (
            SELECT (payload ->> 'notification_id')::bigint FROM (
                SELECT CASE WHEN pg_input_is_valid(result, 'jsonb')
                    THEN result::jsonb ELSE NULL END AS payload
                FROM task WHERE task_type = 'market_review'
            ) AS retired_results
            WHERE jsonb_typeof(payload -> 'notification_id') = 'number'
                AND (payload ->> 'notification_id') ~ '^[1-9][0-9]{0,17}$'
        )""")
        op.execute("-- Private task/audit log cleanup requires normal online Alembic execution")
    else:
        records = (
            op.get_bind()
            .execute(sa.select(tasks.c.task_log, tasks.c.result).where(tasks.c.task_type == "market_review"))
            .all()
        )
        for _, raw in records:
            try:
                result = json.loads(raw or "null")
            except (ValueError, TypeError):
                continue
            value = result.get("notification_id") if isinstance(result, dict) else None
            if type(value) is int and value > 0:
                notification_ids.append(value)
        _purge_files([row.task_log for row in records])
    owned_report = sa.and_(messages.c.route_type == "report", messages.c.title.in_(("🎯 大盘复盘", "🎯 Market Review")))
    owned_error = sa.and_(
        messages.c.route_type == "system_error",
        messages.c.content.contains("\n- 类型：market_review\n", autoescape=True),
    )
    op.execute(messages.delete().where(sa.or_(owned_report, owned_error, messages.c.id.in_(notification_ids))))
    op.execute(usage.delete().where(usage.c.call_type == "market_review"))
    op.execute(tasks.delete().where(tasks.c.task_type == "market_review"))


def downgrade():
    raise RuntimeError("Manual market review history deletion is irreversible")
