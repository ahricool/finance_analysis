"""Retire CN/US Trade Engine and its dedicated history; preserve portfolio facts."""

import fcntl
import json
import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0087_retire_trade_engine"
down_revision = "0086_retire_news"
branch_labels = None
depends_on = None

JOB_IDS = ("trade_engine_cn", "trade_engine_us")
TASK_TYPES = ("scheduled_trade_engine_cn", "scheduled_trade_engine_us")
CALL_TYPE = "trade_engine_market"


def _purge_files(task_logs):
    from finance_analysis.core.paths import get_log_dir

    root = get_log_dir().resolve()
    paths = set()
    for name in task_logs:
        if name:
            path = (root / name).resolve()
            if path.is_relative_to(root) and path.is_file():
                paths.add(path)
    prefixes = ("A股交易引擎_", "美股交易引擎_", *JOB_IDS, *("scheduled." + name for name in JOB_IDS))
    for folder in ("celery", "scheduler"):
        for prefix in prefixes:
            for path in (root / folder).glob(prefix.rstrip("_") + "_*.log"):
                if not path.is_symlink() and path.resolve().is_relative_to(root):
                    paths.add(path)
    for path in paths:
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
                if not isinstance(row, dict) or row.get("call_type") != CALL_TYPE:
                    kept.append(line)
            if len(kept) != len(lines):
                handle.seek(0)
                handle.writelines(kept)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())


def _clean_mutation_receipts(bind):
    receipts = sa.table(
        "portfolio_mutation", sa.column("uid"), sa.column("operation_id"), sa.column("response_json")
    )
    for uid, operation_id, raw in bind.execute(sa.select(receipts)):
        try:
            payload = json.loads(raw or "null")
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and "trade_engine_enabled" in payload:
            del payload["trade_engine_enabled"]
            bind.execute(
                receipts.update()
                .where(receipts.c.uid == uid, receipts.c.operation_id == operation_id)
                .values(response_json=json.dumps(payload, ensure_ascii=False))
            )


def upgrade():
    offline = op.get_context().as_sql
    bind = None if offline else op.get_bind()
    tables = None if offline else set(sa.inspect(bind).get_table_names())
    tasks = sa.table("task", sa.column("task_type"), sa.column("scheduler_job_id"), sa.column("task_log"))
    owned_task = sa.or_(tasks.c.task_type.in_(TASK_TYPES), tasks.c.scheduler_job_id.in_(JOB_IDS))
    if not offline:
        logs = bind.scalars(sa.select(tasks.c.task_log).where(owned_task)).all() if "task" in tables else []
        _purge_files(logs)
    else:
        op.execute("-- Task/audit file cleanup requires normal online Alembic execution")

    if offline or "notification" in tables:
        messages = sa.table(
            "notification", sa.column("id"), sa.column("title"), sa.column("route_type"), sa.column("content")
        )
        owned = [sa.and_(messages.c.route_type == "alert", messages.c.title == "交易引擎")]
        owned.extend(
            sa.and_(
                messages.c.route_type == "system_error",
                messages.c.content.contains(f"\n- 类型：{kind}\n", autoescape=True),
            )
            for kind in TASK_TYPES
        )
        if offline or "trade_signal" in tables:
            signals = sa.table("trade_signal", sa.column("notification_id"))
            owned.append(messages.c.id.in_(sa.select(signals.c.notification_id)))
        op.execute(messages.delete().where(sa.or_(*owned)))
    if offline or "llm_usage" in tables:
        usage = sa.table("llm_usage", sa.column("call_type"))
        op.execute(usage.delete().where(usage.c.call_type == CALL_TYPE))
    if offline or "task" in tables:
        op.execute(tasks.delete().where(owned_task))

    # Keep mutation receipts (and their request hashes) so old trades remain idempotent.
    if offline:
        op.execute("""UPDATE portfolio_mutation
            SET response_json = (response_json::jsonb - 'trade_engine_enabled')::text
            WHERE CASE WHEN pg_input_is_valid(response_json, 'jsonb')
                THEN jsonb_typeof(response_json::jsonb) = 'object'
                    AND response_json::jsonb ? 'trade_engine_enabled'
                ELSE false END""")
    elif "portfolio_mutation" in tables:
        _clean_mutation_receipts(bind)
    for name in ("trade_signal", "trade_llm_state"):
        op.execute(sa.text(f"DROP TABLE IF EXISTS {name}"))
    if offline:
        op.execute("ALTER TABLE portfolio_position DROP COLUMN IF EXISTS trade_engine_enabled")
    elif "portfolio_position" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("portfolio_position")}
        if "trade_engine_enabled" in columns:
            op.drop_column("portfolio_position", "trade_engine_enabled")


def downgrade():
    raise RuntimeError("Trade Engine history deletion is irreversible")
