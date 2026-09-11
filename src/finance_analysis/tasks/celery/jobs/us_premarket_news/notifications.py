# -*- coding: utf-8 -*-
"""Notification rendering for US premarket news intelligence."""

from __future__ import annotations

import logging
from typing import Dict

from .models import PremarketNewsSummary

logger = logging.getLogger(__name__)


def _impact_by_key(summary: PremarketNewsSummary) -> Dict[str, Dict]:
    return {
        str(item.get("news_id_or_url") or ""): item
        for item in summary.impact_results
        if item.get("news_id_or_url")
    }


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
    """Sends the Top news notification."""

    def send_notification(self, summary: PremarketNewsSummary) -> bool:
        try:
            from finance_analysis.notification.service import NotificationService

            return NotificationService().send(
                render_notification(summary),
                route_type="report",
                severity="info",
                dedup_key=f"us_premarket_news:{summary.started_at.strftime('%Y%m%d')}",
                cooldown_key="us_premarket_news",
            )
        except Exception as exc:
            logger.warning("发送美股盘前新闻情报通知失败: %s", exc, exc_info=True)
            return False
