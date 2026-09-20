# -*- coding: utf-8 -*-
"""LLM reviews deterministic TradeSignalCandidates. It cannot change action/target."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from ..llm import LLMClient, LLMError, LLMRequest, parse_llm_batch_results  # pragma: allowlist secret
from .models import ReviewDecision, TradeSignalCandidate  # pragma: allowlist secret

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是持仓交易信号复核器。\n"
    "确定性策略已经决定了 action 和 target，你无权修改交易动作和目标数量。\n"
    "你的职责只有：\n"
    "1. CONFIRM：没有发现足以否决该信号的重要事实。\n"
    "2. REJECT：发现明确且有根据的事实，说明该信号当前不应发布。\n"
    "你可以使用 Web Search 核实与当前股票直接相关的最新重大信息"
    "（财报/业绩、停牌、监管/诉讼/并购、可能解释异常波动的公司新闻）。\n"
    "不要搜索无关宏观、整个市场选股、板块排名或全市场扫描。\n"
    "不要推荐其它股票。不要产生 BUY。不要扩大仓位。\n"
    "如果你对策略本身、市场情况或其它风险有额外看法，写在 comment 中，"
    "但不能修改 action 或 target。\n"
    "只输出 JSON。"
)

_PROMPT = """下面是同一轮由确定性策略产生的持仓交易信号候选。请逐条独立判断该信号是否应发布。
decision 只能是 CONFIRM 或 REJECT。
不要返回 action 或 target；即使返回也会被忽略。
如有必要，仅对该 candidate 的 symbol 进行 Web Search 复核。
只输出 JSON object，不要 markdown：
{{"results":[{{"id":"signal_key","decision":"CONFIRM","reason":"...","comment":null}}]}}

输入：
{payload}
"""


def _payload_for(candidate: TradeSignalCandidate, extras: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.signal_key,
        "market": candidate.market,
        "symbol": candidate.symbol,
        "strategy": candidate.strategy_key,
        "action": candidate.action,
        "target_quantity": None
        if candidate.suggested_target_quantity is None
        else format(candidate.suggested_target_quantity, "f"),
        "severity": candidate.severity,
        "reason": candidate.reason,
        "evidence": candidate.evidence,
        "search_scope": f"only {candidate.symbol}",
        **extras,
    }


class TradeSignalReviewer:
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

    def review(
        self,
        candidates: Sequence[TradeSignalCandidate],
        *,
        extras: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, ReviewDecision]:
        extras = extras or {}
        if not candidates:
            return {}
        client = self._client_or_none()
        if client is None:
            return {
                item.signal_key: ReviewDecision("REJECT", "llm_unavailable", failed=True)
                for item in candidates
            }
        payload = [_payload_for(item, extras.get(item.signal_key) or {}) for item in candidates]
        try:
            result = client.complete_text(
                LLMRequest(
                    prompt=_PROMPT.format(payload=json.dumps(payload, ensure_ascii=False, default=str)),
                    system_prompt=_SYSTEM,
                    call_type="trade_engine_review",
                    temperature=0,
                    web_search=True,
                ),
                validator=lambda text: parse_llm_batch_results(text, strict=True),
            )
            rows = parse_llm_batch_results(result.text)
        except (LLMError, ValueError) as exc:
            logger.warning("Trade Engine LLM review failed: %s", type(exc).__name__)
            return {
                item.signal_key: ReviewDecision("REJECT", "llm_failed", failed=True) for item in candidates
            }
        by_id = {str(item.get("id") or ""): item for item in rows}
        decisions: dict[str, ReviewDecision] = {}
        for candidate in candidates:
            raw = by_id.get(candidate.signal_key)
            if raw is None:
                decisions[candidate.signal_key] = ReviewDecision("REJECT", "llm_missing_result", failed=True)
                continue
            verdict = str(raw.get("decision") or "").strip().upper()
            if verdict not in {"CONFIRM", "REJECT"}:
                verdict = "REJECT"
            comment = raw.get("comment")
            comment_text = None if comment is None else str(comment).strip()[:600] or None
            decisions[candidate.signal_key] = ReviewDecision(
                verdict,  # type: ignore[arg-type]
                str(raw.get("reason") or "")[:600],
                comment_text,
            )
        return decisions
