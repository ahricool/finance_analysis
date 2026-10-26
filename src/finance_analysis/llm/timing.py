"""Request timing shared with a task's report, including copied thread contexts."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class TimingCollector:
    rows: list[dict] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    def add(self, row):
        with self.lock:
            self.rows.append(dict(row))

    def snapshot(self, uid=None):
        with self.lock:
            return [dict(row) for row in self.rows if uid is None or row.get("uid") in (None, uid)]


CURRENT_TIMINGS: ContextVar[TimingCollector | None] = ContextVar("llm_timings", default=None)


def timing_rows(uid=None):
    collector = CURRENT_TIMINGS.get()
    return [{k: v for k, v in row.items() if k != "uid"} for row in collector.snapshot(uid)] if collector else []


def timing_markdown(uid=None, rows=None):
    rows = timing_rows(uid) if rows is None else rows
    if not rows:
        return ""
    lines = [
        "### LLM 调用耗时",
        "",
        "截至本报告生成；耗时包含连接与清理，重试等待单列。并发调用耗时不能直接相加作为任务耗时。",
        "",
    ]
    for row in rows:
        attempts = " → ".join(
            f"{a['provider']} 第{a['attempt']}次 {a['duration_ms'] / 1000:.2f}s（{a['status']}）"
            for a in row["attempts"]
        )
        lines.append(
            f"- {row['call_type']} [{row['request_id'][:8]}]：{attempts}；"
            f"等待 {row['retry_wait_ms'] / 1000:.2f}s；总计 {row['duration_ms'] / 1000:.2f}s"
        )
    return "\n".join(lines)


def without_timings(content):
    if "### LLM 调用耗时" not in content:
        return content
    return content.split("### LLM 调用耗时", 1)[0].rstrip()


def append_timings(content, uid=None):
    report = timing_markdown(uid)
    if not report:
        return content
    # A task's final aggregate includes failed requests too. Preserve saved
    # historical timing when rendering outside an active task context.
    content = without_timings(content)
    return content + "\n\n" + report
