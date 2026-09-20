# -*- coding: utf-8 -*-
"""Format and send Trade Engine alerts through existing global channels."""

from __future__ import annotations

from typing import Sequence

from finance_analysis.notification.service import NotificationResult, NotificationService  # pragma: allowlist secret
from finance_analysis.trade_engine.models import TradeSignal  # pragma: allowlist secret


def render_trade_message(*, market: str, signals: Sequence[TradeSignal]) -> tuple[str, str]:
    lines = [f"Trade Engine {market}"]
    for item in signals:
        lines.append(
            f"{item.symbol or '-'} action={item.action} target={item.suggested_target_quantity} "
            f"strategy={item.strategy_key} reason={item.reason}"
        )
    body = "\n".join(lines)
    lowered = body.lower()
    for forbidden in ("refresh_token", "access_token", "code_verifier", "spreadsheet", "oauth"):
        if forbidden in lowered:
            body = "交易引擎提醒已生成，详情见站内消息。"
            break
    return "交易引擎", body


def push_after_commit(
    *,
    notification_id: int,
    title: str,
    content: str,
    service: NotificationService | None = None,
) -> NotificationResult:
    notifier = service or NotificationService()
    return notifier.push_existing(content, notification_id=notification_id, title=title, route_type="alert")
