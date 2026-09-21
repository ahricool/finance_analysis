# -*- coding: utf-8 -*-
"""Format one market-level Trade Engine notification when targets actually change."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from ..notification.service import NotificationResult, NotificationService  # pragma: allowlist secret
from .models import PortfolioRiskFacts, StrategySignal, TradeSignal  # pragma: allowlist secret


def _qty(value) -> str:
    return format(value, "f") if value is not None else "-"


def _pct(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{(value * 100):.1f}%"


def render_trade_message(
    *,
    market: str,
    signals: Sequence[TradeSignal],
    strategy_signals: Sequence[StrategySignal] | None = None,
    portfolio_risk: PortfolioRiskFacts | None = None,
    contexts: dict[str, Any] | None = None,
    quotes: dict[str, Any] | None = None,
) -> tuple[str, str]:
    del contexts, quotes
    lines = [f"【Trade Engine · {market}】", ""]
    if portfolio_risk is not None:
        lines.append("Portfolio:")
        lines.append(f"当前总仓位 {_pct(portfolio_risk.gross_exposure)}")
        lines.append(f"目标风险上限 {_pct(portfolio_risk.max_gross_exposure)}")
        lines.append("")
    grouped: dict[str, list[StrategySignal]] = {}
    for item in strategy_signals or ():
        grouped.setdefault(item.symbol or "", []).append(item)
    for item in signals:
        lines.append(item.symbol or "-")
        current = (item.evidence or {}).get("current_quantity")
        target = _qty(item.suggested_target_quantity)
        lines.append(f"当前：{current or '-'}股")
        lines.append(f"目标：{target}股")
        lines.append(f"动作：{item.action}")
        lines.append("")
        lines.append("Strategy意见：")
        opinions = grouped.get(item.symbol or "") or []
        if not opinions:
            lines.append("• 本轮无机械交易信号")
        for proposal in opinions:
            if proposal.action in {"ADD", "BUY"} and proposal.suggested_quantity is not None:
                detail = f"{proposal.action} +{_qty(proposal.suggested_quantity)}"
            elif proposal.suggested_target_quantity is not None:
                detail = f"{proposal.action} → {_qty(proposal.suggested_target_quantity)}"
            else:
                detail = proposal.action
            lines.append(f"• {proposal.strategy_key}：{detail}")
            lines.append(f"  {proposal.reason}")
        facts = None if portfolio_risk is None else portfolio_risk.positions.get(item.symbol or "")
        lines.append("Portfolio Risk：")
        if facts is None:
            lines.append("• 无单独持仓风险事实")
        else:
            lines.append(f"• 当前权重{_pct(facts.weight)}，限制{_pct(facts.max_weight)}")
            lines.append(f"• 当前open risk {_pct(facts.open_risk)}，限制{_pct(facts.risk_limit)}")
        lines.append("LLM最终：")
        lines.append(f"{item.action} → {target}")
        lines.append("理由：")
        lines.append(item.llm_reason or item.reason)
        lines.append("")
    return "交易引擎", "\n".join(lines).strip()


def push_after_commit(
    *,
    notification_id: int,
    title: str,
    content: str,
    service: NotificationService | None = None,
) -> NotificationResult:
    notifier = service or NotificationService()
    return notifier.push_existing(content, notification_id=notification_id, title=title, route_type="alert")
