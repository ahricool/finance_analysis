# -*- coding: utf-8 -*-
"""Format Trade Engine alerts. Trade decisions and portfolio warnings stay distinct."""

from __future__ import annotations

from typing import Any, Sequence

from ..notification.service import NotificationResult, NotificationService  # pragma: allowlist secret
from .models import PortfolioWarning, TradeSignal  # pragma: allowlist secret


def _qty(value) -> str:
    return format(value, "f") if value is not None else "-"


def render_trade_message(
    *,
    market: str,
    signals: Sequence[TradeSignal],
    contexts: dict[str, Any] | None = None,
    quotes: dict[str, Any] | None = None,
) -> tuple[str, str]:
    contexts = contexts or {}
    quotes = quotes or {}
    lines: list[str] = []
    for item in signals:
        context = contexts.get(item.position_id or "")
        position = None if context is None else context.position
        quote = quotes.get(item.symbol or "")
        price = None if quote is None else quote.price
        cost = None if position is None else position.average_cost
        qty = None if position is None else position.quantity
        lines.append(f"【Trade Engine · {item.symbol or '-'}】")
        if qty is not None and price is not None:
            lines.append(f"当前持仓：{_qty(qty)}股 @ {price}")
        elif qty is not None:
            lines.append(f"当前持仓：{_qty(qty)}股")
        if cost is not None:
            lines.append(f"平均成本：{cost}")
        lines.append("策略信号：")
        proposals = (item.evidence or {}).get("proposals") or []
        if not proposals:
            lines.append(f"• {item.strategy_key}")
            lines.append(f"  {item.action} → {_qty(item.suggested_target_quantity)}股")
            lines.append(f"  原因：{item.reason}")
        for proposal in proposals:
            action = proposal.get("action")
            target = proposal.get("target_quantity")
            quantity = proposal.get("quantity")
            if action in {"ADD", "BUY"} and quantity:
                detail = f"{action} +{quantity}股"
            elif target is not None:
                detail = f"{action} → {target}股"
            else:
                detail = str(action)
            lines.append(f"• {proposal.get('strategy')}")
            lines.append(f"  {detail}")
            lines.append(f"  原因：{proposal.get('reason') or '-'}")
        final = item.action
        if item.suggested_target_quantity is not None:
            final = f"{item.action} → {_qty(item.suggested_target_quantity)}股"
        elif item.suggested_quantity is not None:
            final = f"{item.action} +{_qty(item.suggested_quantity)}股"
        lines.append("LLM最终判断：")
        lines.append(final)
        lines.append("理由：")
        lines.append(item.llm_reason or item.reason)
        lines.append("")
    body = _scrub("\n".join(lines).strip())
    return "交易引擎", body


def render_warning_message(*, market: str, warnings: Sequence[PortfolioWarning]) -> tuple[str, str]:
    title = "A股账户风险" if market == "CN" else "美股账户风险"
    lines = [f"【{title}】", ""]
    for item in warnings:
        current_pct = f"{(item.current * 100):.0f}%"
        limit_pct = f"{(item.limit * 100):.0f}%"
        if item.kind == "max_gross_exposure":
            lines.append(f"总仓位：{current_pct}")
            lines.append(f"限制：{limit_pct}")
        elif item.kind == "max_symbol_weight":
            lines.append(f"{item.symbol or '-'}仓位：{current_pct}")
            lines.append(f"限制：{limit_pct}")
        elif item.kind == "risk_per_symbol":
            lines.append(f"{item.symbol or '-'}计划风险：{current_pct}")
            lines.append(f"限制：{limit_pct}")
        else:
            lines.append(f"{item.reason}：{current_pct} / 限制 {limit_pct}")
        lines.append("")
    return title, _scrub("\n".join(lines).strip())


def _scrub(body: str) -> str:
    lowered = body.lower()
    for forbidden in ("refresh_token", "access_token", "code_verifier", "spreadsheet", "oauth"):
        if forbidden in lowered:
            return "交易引擎提醒已生成，详情见站内消息。"
    return body


def push_after_commit(
    *,
    notification_id: int,
    title: str,
    content: str,
    service: NotificationService | None = None,
) -> NotificationResult:
    notifier = service or NotificationService()
    return notifier.push_existing(content, notification_id=notification_id, title=title, route_type="alert")
