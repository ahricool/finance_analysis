# -*- coding: utf-8 -*-
"""Format and send Trade Engine alerts through existing global channels."""

from __future__ import annotations

from typing import Any, Sequence

from ..notification.service import NotificationResult, NotificationService  # pragma: allowlist secret
from .models import TradeSignal  # pragma: allowlist secret


def render_trade_message(
    *,
    market: str,
    signals: Sequence[TradeSignal],
    contexts: dict[str, Any] | None = None,
    quotes: dict[str, Any] | None = None,
) -> tuple[str, str]:
    contexts = contexts or {}
    quotes = quotes or {}
    lines = [f"Trade Engine {market}"]
    for item in signals:
        context = contexts.get(item.position_id or "")
        position = None if context is None else context.position
        quote = quotes.get(item.symbol or "")
        price = None if quote is None else quote.price
        cost = None if position is None else position.average_cost
        qty = None if position is None else position.quantity
        pnl = None
        if price is not None and cost is not None and cost > 0:
            pnl = (price / cost - 1) * 100
        hard = bool((item.evidence or {}).get("hard")) or item.action == "EXIT" and not item.reviewed_by_llm
        lines.append(f"{item.symbol or '-'} {item.action}")
        if qty is not None:
            lines.append(f"当前持仓 {format(qty, 'f')} 股")
        if price is not None:
            lines.append(f"当前价格 {format(price, 'f')}")
        if cost is not None:
            lines.append(f"平均成本 {format(cost, 'f')}")
        if pnl is not None:
            lines.append(f"当前收益 {format(pnl, 'f')}%")
        lines.append(f"Strategy {item.strategy_key} {item.strategy_version}")
        if item.suggested_target_quantity is not None:
            lines.append(f"建议目标数量 {format(item.suggested_target_quantity, 'f')}")
        lines.append(f"确定性原因 {item.deterministic_reason or item.reason}")
        if item.llm_reason:
            lines.append(f"LLM复核 {item.llm_reason}")
        if item.llm_comment:
            lines.append(f"LLM意见 {item.llm_comment}")
        if hard:
            lines.append("硬保护规则触发")
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
