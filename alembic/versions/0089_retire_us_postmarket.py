"""Retire the US postmarket report and its dedicated history; retain shared research inputs."""

import fcntl
import json
import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0089_retire_us_postmarket"
down_revision = "0088_holdings_review"
branch_labels = None
depends_on = None

TASK_TYPE = "scheduled_us_postmarket_review"
JOB_ID = "analysis_us_postmarket_review"
CALL_TYPES = ("us_postmarket_review",)


def _purge_files(task_logs):
    from finance_analysis.core.paths import get_log_dir

    root = get_log_dir().resolve()
    paths = []
    for name in task_logs:
        if not name:
            continue
        candidate = root / name
        if candidate.is_symlink():
            continue
        path = candidate.resolve()
        if path.is_relative_to(root) and path.is_file():
            paths.append(path)
    for folder in ("celery", "scheduler"):
        for prefix in ("美股收盘复盘_", JOB_ID + "_", "scheduled." + JOB_ID + "_"):
            for path in (root / folder).glob(prefix + "*.log"):
                if not path.is_symlink() and path.resolve().is_relative_to(root):
                    paths.append(path)
    for path in set(paths):
        path.unlink(missing_ok=True)
    audit_dir = Path(os.getenv("LLM_LOG_DIR") or root / "llm").expanduser()
    for path in (*audit_dir.glob("*.log"), *audit_dir.glob("*.jsonl")):
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
        # JSON (not JSONB) preserves numeric spelling: exponent/decimal IDs stay invalid.
        op.execute("""DELETE FROM notification WHERE id IN (
            SELECT (payload ->> 'notification_id')::bigint FROM (
                SELECT CASE WHEN pg_input_is_valid(result, 'json')
                    THEN result::json ELSE NULL END AS payload
                FROM task WHERE task_type = 'scheduled_us_postmarket_review'
                    OR scheduler_job_id = 'analysis_us_postmarket_review'
            ) AS retired_results
            WHERE json_typeof(payload -> 'notification_id') = 'number'
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
        owned_report = sa.and_(
            messages.c.route_type == "report",
            sa.or_(
                messages.c.title.in_(("美股收盘复盘", "🇺🇸 美股收盘复盘", "US Postmarket Review")),
                messages.c.title.startswith("美股收盘复盘 - ", autoescape=True),
                messages.c.title.startswith("🇺🇸 美股收盘复盘 - ", autoescape=True),
                messages.c.title.startswith("US Postmarket Review - ", autoescape=True),
                messages.c.content.startswith("# 美股收盘复盘 - ", autoescape=True),
            ),
        )
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
    if offline or "timeline_entries" in tables:
        legacy = sa.table("timeline_entries", sa.column("entry_type"))
        op.execute(legacy.delete().where(legacy.c.entry_type == "us_postmarket"))
    if offline or {"universe_member", "universe"}.issubset(tables):
        # These ETFs still serve earnings context and core index coverage; only rename ownership.
        members = sa.table("universe_member", sa.column("source", sa.String), sa.column("universe_id", sa.Integer))
        universes = sa.table("universe", sa.column("id"), sa.column("key"))
        op.execute(members.update().where(
            members.c.source == "US_POSTMARKET_REVIEW",
            members.c.universe_id.in_(sa.select(universes.c.id).where(universes.c.key == "us_daily_sync")),
        ).values(source="US_RESEARCH_CONTEXT"))


def downgrade():
    raise RuntimeError("US postmarket report history deletion is irreversible")
