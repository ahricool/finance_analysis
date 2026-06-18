# -*- coding: utf-8 -*-
"""Calendar and notification rendering for US premarket news intelligence."""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from .models import PremarketNewsSummary

logger = logging.getLogger(__name__)


def _impact_by_key(summary: PremarketNewsSummary) -> Dict[str, Dict]:
    return {
        str(item.get("news_id_or_url") or ""): item
        for item in summary.impact_results
        if item.get("news_id_or_url")
    }


def render_calendar_content(summary: PremarketNewsSummary) -> str:
    elapsed = (summary.finished_at - summary.started_at).total_seconds()
    lines: List[str] = [
        "## 美股盘前新闻情报",
        "",
        f"- 执行时间：{summary.started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 结束时间：{summary.finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 耗时：{elapsed:.2f} 秒",
        f"- symbols 数量：{summary.symbols_count}",
        f"- 抓取新闻数量：{summary.fetched_news_count}",
        f"- 新增入库数量：{summary.inserted_news_count}",
        f"- 候选新闻数量：{summary.candidates_count}",
        f"- LLM 筛选数量：{len(summary.important_news)}",
    ]
    if summary.warnings:
        lines.extend(["", "### Warning 摘要", "", *[f"- {item}" for item in summary.warnings[:20]]])
    if summary.errors:
        lines.extend(["", "### 错误摘要", "", *[f"- {item}" for item in summary.errors[:20]]])

    impact_map = _impact_by_key(summary)
    if summary.important_news:
        lines.extend(["", "### Top 10 新闻", ""])
        for index, item in enumerate(summary.important_news, start=1):
            key = str(item.get("news_id_or_url") or "")
            impact = impact_map.get(key, {})
            symbols = ", ".join(item.get("related_symbols") or impact.get("related_symbols") or [])
            lines.extend(
                [
                    f"{index}. **{item.get('title', '-')}**",
                    f"   - 相关新闻标识：{key}",
                    f"   - 相关标的：{symbols or '-'}",
                    f"   - 重要性：{item.get('importance_score', '-')} / 10，{item.get('event_type', '-')}",
                    f"   - 重要性原因：{item.get('importance_reason', '-')}",
                    (
                        f"   - 影响方向：{impact.get('impact', '-')}，"
                        f"score={impact.get('impact_score', '-')}，confidence={impact.get('confidence', '-')}"
                    ),
                    f"   - 影响原因：{impact.get('reason', '-')}",
                ]
            )

    lines.extend(
        [
            "",
            "### 结构化 JSON",
            "",
            "```json",
            json.dumps(
                {
                    "symbols": summary.symbols,
                    "fetched_news_count": summary.fetched_news_count,
                    "inserted_news_count": summary.inserted_news_count,
                    "important_news": summary.important_news,
                    "impact_results": summary.impact_results,
                    "warnings": summary.warnings,
                    "errors": summary.errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
    )
    return "\n".join(lines)


def render_notification(summary: PremarketNewsSummary) -> str:
    impact_map = _impact_by_key(summary)
    lines = [
        "**美股盘前新闻情报**",
        "",
        (
            f"symbols {summary.symbols_count} | 抓取 {summary.fetched_news_count} | "
            f"新增 {summary.inserted_news_count} | 候选 {summary.candidates_count}"
        ),
    ]
    if summary.warnings:
        lines.append(f"warning：{'; '.join(summary.warnings[:3])}")
    if summary.errors:
        lines.append(f"错误：{'; '.join(summary.errors[:3])}")

    if summary.important_news:
        lines.extend(["", "### Top 新闻"])
        for item in summary.important_news[:10]:
            key = str(item.get("news_id_or_url") or "")
            impact = impact_map.get(key, {})
            symbols = ", ".join(item.get("related_symbols") or impact.get("related_symbols") or [])
            lines.append(
                f"- **{item.get('title', '-')}** | {symbols or '-'} | "
                f"impact={impact.get('impact', '-')} score={impact.get('impact_score', '-')}"
            )
            reason = impact.get("reason") or item.get("importance_reason")
            if reason:
                lines.append(f"  - {reason}")
    else:
        lines.extend(["", "未筛选出高重要性新闻，可能是 LLM 未配置或候选新闻不足。"])
    return "\n".join(lines)


class PremarketNewsReporter:
    """Persists the task summary to calendar and sends notifications."""

    def record_to_calendar(self, summary: PremarketNewsSummary) -> Optional[int]:
        try:
            from src.repositories.calendar_repo import CalendarRepo
            from src.repositories.user_repo import UserRepository

            uid = UserRepository().ensure_default_admin()
            title = (
                f"美股盘前新闻情报：symbols {summary.symbols_count}，"
                f"top {len(summary.important_news)}，新增 {summary.inserted_news_count}"
            )
            entry = CalendarRepo().create(
                uid=uid,
                time=summary.finished_at,
                title=title[:120],
                content=render_calendar_content(summary),
                type="scheduled_us_premarket_news",
            )
            return int(getattr(entry, "id", 0) or 0)
        except Exception as exc:
            logger.warning("写入美股盘前新闻情报日历失败: %s", exc, exc_info=True)
            return None

    def send_notification(self, summary: PremarketNewsSummary) -> bool:
        try:
            from src.notification import NotificationService

            return NotificationService().send(
                render_notification(summary),
                email_stock_codes=summary.symbols,
                route_type="report",
                severity="info",
                dedup_key=f"us_premarket_news:{summary.started_at.strftime('%Y%m%d')}",
                cooldown_key="us_premarket_news",
            )
        except Exception as exc:
            logger.warning("发送美股盘前新闻情报通知失败: %s", exc, exc_info=True)
            return False
