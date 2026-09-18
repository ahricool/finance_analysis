# -*- coding: utf-8 -*-
"""Format and send portfolio-risk alerts through the existing global channels."""

from __future__ import annotations

from typing import Any

from finance_analysis.notification.service import NotificationResult, NotificationService  # pragma: allowlist secret


def render_risk_message(*, uid: int, snapshot_generation: int, results: list[dict[str, Any]]) -> tuple[str, str]:
    lines = [f"持仓风控提醒 generation={snapshot_generation}"]
    for item in results:
        lines.append(
            f"{item.get('symbol')} {item.get('account_id')}/{item.get('position_id')} "
            f"action={item.get('action')} target={item.get('position_target')} "
            f"vwap={item.get('vwap_mode') or 'UNAVAILABLE'} reason={item.get('reason')}"
        )
        if item.get("legs"):
            for leg in item["legs"]:
                lines.append(
                    f"  {leg.get('role')} {leg.get('leg_id')} qty={leg.get('quantity')} "
                    f"target={leg.get('target')} stop={leg.get('active_stop')} stage={leg.get('stage')}"
                )
    body = "\n".join(lines)
    lowered = body.lower()
    for forbidden in ("refresh_token", "access_token", "code_verifier", "spreadsheet", "oauth"):
        if forbidden in lowered:
            body = "持仓风控提醒已生成，详情见站内消息。"
            break
    return "持仓风控", body


def push_after_commit(
    *,
    notification_id: int,
    title: str,
    content: str,
    service: NotificationService | None = None,
) -> NotificationResult:
    notifier = service or NotificationService()
    return notifier.push_existing(content, notification_id=notification_id, title=title, route_type="alert")
