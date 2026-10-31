"""Retire news collection, judgments, and their dedicated history."""

import fcntl
import json
import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0086_retire_news"
down_revision = "0085_retire_market_review"
branch_labels = None
depends_on = None

TASK_TYPE = "scheduled_us_premarket_news"
JOB_ID = "analysis_us_premarket_news"
CALL_TYPES = ("us_premarket_news_importance", "us_premarket_news_impact")


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
        for prefix in ("美股盘前新闻情报_", JOB_ID + "_", "scheduled." + JOB_ID + "_"):
            for path in (root / folder).glob(prefix + "*.log"):
                if not path.is_symlink() and path.resolve().is_relative_to(root):
                    paths.append(path)
    for path in set(paths):
        path.unlink(missing_ok=True)
    audit_dir = Path(os.getenv("LLM_LOG_DIR") or root / "llm").expanduser()
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
                if not isinstance(row, dict) or row.get("call_type") not in CALL_TYPES:
                    kept.append(line)
            if len(kept) != len(lines):
                handle.seek(0)
                handle.writelines(kept)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())


def upgrade():
    offline = op.get_context().as_sql
    tables = None if offline else set(sa.inspect(op.get_bind()).get_table_names())
    tasks = sa.table(
        "task", sa.column("task_type"), sa.column("scheduler_job_id"), sa.column("task_log"), sa.column("result")
    )
    owned_task = sa.or_(tasks.c.task_type == TASK_TYPE, tasks.c.scheduler_job_id == JOB_ID)
    messages = sa.table(
        "notification", sa.column("id", sa.Integer), sa.column("title"), sa.column("route_type"), sa.column("content")
    )
    notification_ids = []
    if offline:
        op.execute("""DELETE FROM notification WHERE id IN (
            SELECT (payload ->> 'notification_id')::bigint FROM (
                SELECT CASE WHEN pg_input_is_valid(result, 'jsonb')
                    THEN result::jsonb ELSE NULL END AS payload
                FROM task WHERE task_type = 'scheduled_us_premarket_news'
                    OR scheduler_job_id = 'analysis_us_premarket_news'
            ) AS retired_results
            WHERE jsonb_typeof(payload -> 'notification_id') = 'number'
                AND (payload ->> 'notification_id') ~ '^[1-9][0-9]{0,17}$'
        )""")
        op.execute("-- Task/audit file cleanup requires normal online Alembic execution")
    elif "task" in tables:
        records = op.get_bind().execute(sa.select(tasks.c.task_log, tasks.c.result).where(owned_task)).all()
        for _, raw in records:
            try:
                result = json.loads(raw or "null")
            except (ValueError, TypeError):
                continue
            value = result.get("notification_id") if isinstance(result, dict) else None
            if type(value) is int and 0 < value <= 2147483647:
                notification_ids.append(value)
        _purge_files([row.task_log for row in records])
    else:
        _purge_files([])
    if offline or "notification" in tables:
        owned_report = sa.and_(messages.c.route_type == "report", messages.c.title == "美股盘前新闻情报")
        owned_error = sa.and_(
            messages.c.route_type == "system_error",
            messages.c.content.contains(f"\n- 类型：{TASK_TYPE}\n", autoescape=True),
        )
        op.execute(messages.delete().where(sa.or_(owned_report, owned_error, messages.c.id.in_(notification_ids))))
    if offline or "llm_usage" in tables:
        usage = sa.table("llm_usage", sa.column("call_type"))
        op.execute(usage.delete().where(usage.c.call_type.in_(CALL_TYPES)))
    if offline or "task" in tables:
        op.execute(tasks.delete().where(owned_task))
    # Children first. No CASCADE: unrelated data must never be silently removed.
    for name in ("news_analysis", "news_intel_usage", "news_intel"):
        op.execute(sa.text(f"DROP TABLE IF EXISTS {name}"))


def downgrade():
    raise RuntimeError("News history deletion is irreversible")
