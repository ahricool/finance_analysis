# -*- coding: utf-8 -*-
"""LLM reviews deterministic TradeSignalCandidates. It is not a signal generator."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Sequence

from ..llm import LLMClient, LLMError, LLMRequest, parse_llm_batch_results  # pragma: allowlist secret
from .models import ACTION_RANK, ReviewDecision, TradeSignalCandidate  # pragma: allowlist secret

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是持仓交易信号复核器。只判断给定的确定性交易信号是否合理。"
    "不能建议买入或加仓。不能挑选其它股票。不能编造新闻或全市场判断。"
    "只输出 JSON。"
)

_PROMPT = """下面是同一轮由确定性策略产生的持仓交易信号候选。请逐条独立判断该信号是否合理。
decision 只能是 CONFIRM 或 REJECT。
不能输出 BUY，不能把建议目标数量提高到超过候选 target 或当前持仓。
硬保护 EXIT 只可补充解释，不要 REJECT。
只输出 JSON object，不要 markdown：
{{"results":[{{"id":"signal_key","decision":"CONFIRM","action":"WATCH|REDUCE|EXIT","target_quantity":null,"reason":"..."}}]}}

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


def clamp_review(
    candidate: TradeSignalCandidate,
    decision: ReviewDecision,
    *,
    current_quantity: Decimal,
) -> ReviewDecision:
    if candidate.hard:
        return ReviewDecision(
            decision="CONFIRM",
            action=candidate.action,
            target_quantity=candidate.suggested_target_quantity,
            reason=decision.reason or candidate.reason,
            failed=decision.failed,
        )
    if decision.failed:
        return decision
    if decision.decision != "CONFIRM":
        return ReviewDecision("REJECT", candidate.action, candidate.suggested_target_quantity, decision.reason)
    action = decision.action if decision.action in {"WATCH", "REDUCE", "EXIT"} else candidate.action
    if ACTION_RANK.get(action, 0) < ACTION_RANK.get(candidate.action, 0):
        action = candidate.action
    target = decision.target_quantity if decision.target_quantity is not None else candidate.suggested_target_quantity
    cap = current_quantity
    if candidate.suggested_target_quantity is not None:
        cap = min(cap, candidate.suggested_target_quantity)
    if target is not None:
        if target < 0:
            target = Decimal("0")
        if target > cap:
            target = cap
    if candidate.action == "EXIT" or action == "EXIT":
        action = "EXIT"
        target = Decimal("0")
    return ReviewDecision("CONFIRM", action, target, decision.reason or candidate.reason)


def _payload_for(candidate: TradeSignalCandidate, extras: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.signal_key,
        "market": candidate.market,
        "symbol": candidate.symbol,
        "strategy": candidate.strategy_key,
        "action": candidate.action,
        "target_quantity": None if candidate.suggested_target_quantity is None else format(candidate.suggested_target_quantity, "f"),
        "severity": candidate.severity,
        "reason": candidate.reason,
        "evidence": candidate.evidence,
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
                item.signal_key: ReviewDecision("REJECT", item.action, item.suggested_target_quantity, "llm_unavailable", failed=True)
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
                ),
                validator=lambda text: parse_llm_batch_results(text, strict=True),
            )
            rows = parse_llm_batch_results(result.text)
        except (LLMError, ValueError) as exc:
            logger.warning("Trade Engine LLM review failed: %s", type(exc).__name__)
            return {
                item.signal_key: ReviewDecision("REJECT", item.action, item.suggested_target_quantity, "llm_failed", failed=True)
                for item in candidates
            }
        by_id = {str(item.get("id") or ""): item for item in rows}
        decisions: dict[str, ReviewDecision] = {}
        for candidate in candidates:
            raw = by_id.get(candidate.signal_key)
            if raw is None:
                decisions[candidate.signal_key] = ReviewDecision(
                    "REJECT", candidate.action, candidate.suggested_target_quantity, "llm_missing_result", failed=True
                )
                continue
            verdict = str(raw.get("decision") or "").strip().upper()
            if verdict not in {"CONFIRM", "REJECT"}:
                verdict = "REJECT"
            action = str(raw.get("action") or candidate.action).strip().upper()
            if action not in {"WATCH", "REDUCE", "EXIT"}:
                action = candidate.action
            decisions[candidate.signal_key] = ReviewDecision(
                verdict,  # type: ignore[arg-type]
                action,  # type: ignore[arg-type]
                _dec(raw.get("target_quantity")),
                str(raw.get("reason") or "")[:600],
            )
        return decisions
