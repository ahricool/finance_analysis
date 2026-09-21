# -*- coding: utf-8 -*-
"""Market-level LLM decides target quantities for one CN or US portfolio."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Sequence

from ..llm import LLMClient, LLMError, LLMRequest, parse_llm_json_response  # pragma: allowlist secret
from .models import (  # pragma: allowlist secret
    LLM_SUMMARY_MAX,
    MarketDecision,
    MarketTradeDecisionContext,
    PositionTarget,
    StrategySignal,
    TRADE_ACTIONS,
)

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是中线持仓组合的最终决策层。每个市场每轮只调用一次。\n"
    "Strategy Signals 是机械意见，可以互相冲突，也可以每 30 分钟重复出现。\n"
    "Portfolio Risk Facts 是当前客观风险事实，不是必须立刻减仓的强制指令。\n"
    "你必须为当前市场全部持仓给出 target_quantity。\n"
    "增加仓位（target > current）必须有对应 BUY/ADD Strategy Signal，且不能超过该 Signal 允许的最大仓位。\n"
    "当前没有 Entry Strategy，因此不能给空仓或新股票开仓。\n"
    "降低仓位（target < current）可以因为 exit_v1、Portfolio Risk 或重大实时风险事实。\n"
    "trade_engine_enabled=false 的持仓只能作为组合上下文，target 必须等于 current。\n"
    "Web Search 仅限当前市场已有持仓的重大公司新闻、财报、业绩指引、停牌、监管、诉讼、并购或重大事件。\n"
    "禁止全市场选股、寻找新股票、行业榜单扫描或大范围宏观扫描。\n"
    "state_summary 是简洁交易记忆，不是 chain-of-thought，不要保存隐藏推理。\n"
    "只输出 JSON。"
)

_PROMPT = """下面是当前市场组合决策上下文。请给出整个账户的最终 Target Position。
只输出 JSON object，不要 markdown：
{{
  "market": "US",
  "portfolio_reason": "...",
  "positions": [
    {{
      "symbol": "AAPL.US",
      "current_quantity": "1000",
      "target_quantity": "700",
      "reason": "..."
    }}
  ],
  "state_summary": "..."
}}

target_quantity 必须 >= 0。未提到的 enabled 持仓视为 target=current。
Web Search 仅限当前市场已有持仓。
如果 web_search_available=false，不要声称已经检索过网页。

输入：
{payload}
"""


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:
        return None


def _dump(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def serialize_signal(item: StrategySignal) -> dict[str, Any]:
    return {
        "strategy": item.strategy_key,
        "version": item.strategy_version,
        "symbol": item.symbol,
        "position_id": item.position_id,
        "action": item.action,
        "quantity": _dump(item.suggested_quantity),
        "target_quantity": _dump(item.suggested_target_quantity),
        "reason": item.reason,
        "evidence": item.evidence,
    }


def serialize_context(context: MarketTradeDecisionContext) -> dict[str, Any]:
    risk = context.portfolio_risk
    return {
        "market": context.market,
        "cash": _dump(context.cash),
        "nav": _dump(context.nav),
        "gross_exposure": _dump(context.gross_exposure),
        "policy": context.policy,
        "web_search_available": context.web_search_available,
        "search_scope": "current holdings in this market only",
        "positions": list(context.positions),
        "strategy_signals": [serialize_signal(item) for item in context.strategy_signals],
        "portfolio_risk": {
            "nav": _dump(risk.nav),
            "cash": _dump(risk.cash),
            "gross_exposure": _dump(risk.gross_exposure),
            "max_gross_exposure": _dump(risk.max_gross_exposure),
            "total_open_risk": _dump(risk.total_open_risk),
            "total_open_risk_limit": _dump(risk.total_open_risk_limit),
            "valuation_complete": risk.valuation_complete,
            "positions": {
                symbol: {
                    "weight": _dump(row.weight),
                    "max_weight": _dump(row.max_weight),
                    "open_risk": _dump(row.open_risk),
                    "risk_limit": _dump(row.risk_limit),
                }
                for symbol, row in risk.positions.items()
            },
        },
        "previous_llm_state": {
            "summary": context.previous.summary,
            "last_decision": context.previous.last_decision,
            "last_decision_at": None
            if context.previous.last_decision_at is None
            else context.previous.last_decision_at.isoformat(),
        },
        "recent_trade_signals": list(context.recent_signals),
    }


def derive_action(current: Decimal, target: Decimal) -> str:
    if current == 0 and target > 0:
        return "BUY"
    if target > current:
        return "ADD"
    if target == 0 and current > 0:
        return "EXIT"
    if 0 < target < current:
        return "REDUCE"
    return "NO_ACTION"


def _increase_cap(signals: Sequence[StrategySignal], current: Decimal) -> Decimal | None:
    caps: list[Decimal] = []
    for item in signals:
        if item.action not in {"ADD", "BUY"}:
            continue
        if item.suggested_target_quantity is not None:
            caps.append(item.suggested_target_quantity)
        elif item.suggested_quantity is not None:
            caps.append(current + item.suggested_quantity)
    if not caps:
        return None
    return max(caps)


def web_search_supported(client: LLMClient | None) -> bool:
    if client is None:
        return False
    return getattr(client.config, "backend", None) == "api"


class MarketDecisionResolver:
    def __init__(self, *, client: LLMClient | None = None) -> None:
        self._client = client

    def _client_or_none(self) -> LLMClient | None:
        if self._client is not None:
            return self._client
        try:
            client = LLMClient()
        except Exception:
            return None
        if not client.is_available():
            return None
        self._client = client
        return client

    def decide(self, context: MarketTradeDecisionContext) -> MarketDecision:
        client = self._client_or_none()
        if client is None:
            return MarketDecision(context.market, "llm_unavailable", (), "", failed=True)
        payload = serialize_context(context)
        use_search = bool(context.web_search_available and web_search_supported(client))
        try:
            result = client.complete_text(
                LLMRequest(
                    prompt=_PROMPT.format(payload=json.dumps(payload, ensure_ascii=False, default=str)),
                    system_prompt=_SYSTEM,
                    call_type="trade_engine_market",
                    temperature=0,
                    web_search=use_search,
                ),
                validator=lambda text: parse_llm_json_response(text) or (_ for _ in ()).throw(ValueError("empty")),
            )
            parsed = parse_llm_json_response(result.text) or {}
        except (LLMError, ValueError, StopIteration) as exc:
            logger.warning("Trade Engine market LLM failed: %s", type(exc).__name__)
            return MarketDecision(context.market, "llm_failed", (), "", failed=True)
        return validate_market_decision(context, parsed)


def validate_market_decision(context: MarketTradeDecisionContext, parsed: dict[str, Any]) -> MarketDecision:
    reason = str(parsed.get("portfolio_reason") or "")[:1200]
    summary = str(parsed.get("state_summary") or "")[:LLM_SUMMARY_MAX]
    by_symbol = {
        str(item.get("symbol") or ""): item
        for item in parsed.get("positions") or []
        if isinstance(item, dict) and item.get("symbol")
    }
    signals_by_symbol: dict[str, list[StrategySignal]] = {}
    for item in context.strategy_signals:
        if item.symbol:
            signals_by_symbol.setdefault(item.symbol, []).append(item)
    targets: list[PositionTarget] = []
    for row in context.positions:
        symbol = str(row.get("symbol") or "")
        position_id = str(row.get("position_id") or "")
        current = _dec(row.get("quantity")) or Decimal("0")
        enabled = bool(row.get("trade_engine_enabled", True))
        payload = by_symbol.get(symbol) or {}
        target = _dec(payload.get("target_quantity"))
        if target is None:
            target = current
        if target < 0:
            target = Decimal("0")
        if not enabled:
            target = current
        elif target > current:
            cap = _increase_cap(signals_by_symbol.get(symbol) or (), current)
            if cap is None:
                target = current
            elif target > cap:
                target = cap
        action = derive_action(current, target)
        if action not in TRADE_ACTIONS and action != "NO_ACTION":
            target = current
            action = "NO_ACTION"
        targets.append(
            PositionTarget(
                position_id=position_id,
                symbol=symbol,
                current_quantity=current,
                target_quantity=target,
                action=action,  # type: ignore[arg-type]
                reason=str(payload.get("reason") or "")[:800],
            )
        )
    return MarketDecision(context.market, reason, tuple(targets), summary)
