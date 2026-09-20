# -*- coding: utf-8 -*-
"""LLM resolves conflicting Strategy Proposals into one final trade decision."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Sequence

from ..llm import LLMClient, LLMError, LLMRequest, parse_llm_json_response  # pragma: allowlist secret
from .models import FinalDecision, StrategyAssessment, StrategyProposal  # pragma: allowlist secret

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是中线持仓交易的最终裁决器。\n"
    "确定性 Strategy 已经给出 0 到多个明确交易 Proposal（BUY/ADD/REDUCE/EXIT）。\n"
    "你必须综合这些 Proposal、当前持仓，以及必要时针对当前 symbol 的 Web Search，"
    "给出唯一最终动作。\n"
    "最终 action 只能是本轮 Proposal 中出现过的动作，或 NO_ACTION。\n"
    "不能凭空制造 Proposal 里没有的 BUY/ADD/REDUCE/EXIT。\n"
    "ADD/BUY 数量不能超过对应 Proposal 给出的数量；可以保守缩小。\n"
    "REDUCE/EXIT 不能比退出类 Proposal 更激进（目标仓位不能更低）。\n"
    "Web Search 只能辅助裁决当前持仓股票的 Strategy Proposals，"
    "用于核实重大个股新闻、财报、业绩指引、停牌、监管、诉讼、并购或重大公司事件。\n"
    "不要用于全市场选股、行业排名、寻找其它股票或宏观大范围扫描。\n"
    "不要推荐其它股票。不要产生 confidence score。一次裁决即可。\n"
    "只输出 JSON。"
)

_PROMPT = """下面是同一持仓本轮全部 Strategy Proposal。请给出最终交易裁决。
只输出 JSON object，不要 markdown：
{{
  "action": "REDUCE",
  "target_quantity": "700",
  "quantity": null,
  "reason": "...",
  "strategy_assessments": [
    {{"strategy": "exit_v1", "action": "REDUCE", "decision": "ACCEPT", "reason": "..."}},
    {{"strategy": "add_v1", "action": "ADD", "decision": "REJECT", "reason": "..."}}
  ]
}}

action 只能是本轮 proposals 中的动作或 NO_ACTION。
Web Search 仅限当前 symbol。

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


def serialize_proposal(item: StrategyProposal) -> dict[str, Any]:
    return {
        "proposal_key": item.proposal_key,
        "strategy": item.strategy_key,
        "version": item.strategy_version,
        "action": item.action,
        "quantity": None if item.suggested_quantity is None else format(item.suggested_quantity, "f"),
        "target_quantity": None
        if item.suggested_target_quantity is None
        else format(item.suggested_target_quantity, "f"),
        "reason": item.reason,
        "evidence": item.evidence,
    }


class TradeDecisionResolver:
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

    def resolve(
        self,
        proposals: Sequence[StrategyProposal],
        *,
        extras: dict[str, Any] | None = None,
    ) -> FinalDecision:
        rows = list(proposals)
        if not rows:
            return FinalDecision("", None, "NO_ACTION", None, None, "no_proposals")
        position_id = rows[0].position_id or ""
        symbol = rows[0].symbol
        client = self._client_or_none()
        if client is None:
            return FinalDecision(position_id, symbol, "NO_ACTION", None, None, "llm_unavailable", failed=True)
        payload = {
            "symbol": symbol,
            "search_scope": f"only {symbol}",
            "proposals": [serialize_proposal(item) for item in rows],
            **(extras or {}),
        }
        try:
            result = client.complete_text(
                LLMRequest(
                    prompt=_PROMPT.format(payload=json.dumps(payload, ensure_ascii=False, default=str)),
                    system_prompt=_SYSTEM,
                    call_type="trade_engine_resolve",
                    temperature=0,
                    web_search=True,
                ),
                validator=lambda text: parse_llm_json_response(text) or (_ for _ in ()).throw(ValueError("empty")),
            )
            parsed = parse_llm_json_response(result.text) or {}
        except (LLMError, ValueError, StopIteration) as exc:
            logger.warning("Trade Engine LLM resolve failed: %s", type(exc).__name__)
            return FinalDecision(position_id, symbol, "NO_ACTION", None, None, "llm_failed", failed=True)
        return clamp_decision(rows, parsed)


def clamp_decision(proposals: Sequence[StrategyProposal], parsed: dict[str, Any]) -> FinalDecision:
    rows = list(proposals)
    position_id = rows[0].position_id or ""
    symbol = rows[0].symbol
    allowed = {item.action for item in rows}
    action = str(parsed.get("action") or "").strip().upper()
    reason = str(parsed.get("reason") or "")[:800]
    assessments = tuple(
        StrategyAssessment(
            strategy=str(item.get("strategy") or ""),
            action=str(item.get("action") or ""),
            decision=str(item.get("decision") or ""),
            reason=str(item.get("reason") or "")[:400],
        )
        for item in parsed.get("strategy_assessments") or []
        if isinstance(item, dict)
    )
    if action not in allowed:
        return FinalDecision(position_id, symbol, "NO_ACTION", None, None, reason or "action_not_in_proposals", assessments)
    quantity = _dec(parsed.get("quantity"))
    target = _dec(parsed.get("target_quantity"))
    matching = [item for item in rows if item.action == action]
    if action in {"ADD", "BUY"}:
        max_qty = max((item.suggested_quantity for item in matching if item.suggested_quantity is not None), default=None)
        if quantity is None:
            quantity = max_qty
        if max_qty is not None and quantity is not None and quantity > max_qty:
            quantity = max_qty
        if quantity is not None and quantity <= 0:
            return FinalDecision(position_id, symbol, "NO_ACTION", None, None, reason or "quantity_clamped_to_zero", assessments)
        if target is None and quantity is not None:
            current = _dec((matching[0].evidence or {}).get("current_quantity"))
            if current is not None:
                target = current + quantity
        return FinalDecision(position_id, symbol, action, quantity, target, reason, assessments)  # type: ignore[arg-type]
    min_target = min(
        (item.suggested_target_quantity for item in matching if item.suggested_target_quantity is not None),
        default=None,
    )
    if target is None:
        target = min_target
    if min_target is not None and target is not None and target < min_target:
        target = min_target
    if action == "EXIT":
        target = Decimal("0")
    return FinalDecision(position_id, symbol, action, quantity, target, reason, assessments)  # type: ignore[arg-type]
