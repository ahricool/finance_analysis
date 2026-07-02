# -*- coding: utf-8 -*-
"""LLM batch judging for A-share intraday rule candidates.

The rule engine has already filtered candidates; the LLM only reviews them:
is the signal real, what drives it, is it sustainable, what is the risk
(including T+1), and is it worth notifying. It must not invent prices, news or
flows, and must not output absolute buy/sell instructions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from finance_analysis.llm import LLMClient, LLMRequest

from .config import LLM_TIMEOUT

logger = logging.getLogger(__name__)

_VALID_DECISIONS = {"watch", "risk", "ignore"}
_VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}
_VALID_DRIVERS = {"stock_specific", "sector", "index_beta", "policy", "unknown"}
_VALID_QUALITY = {"high", "medium", "low"}

_SYSTEM_PROMPT = (
    "你是 A 股盘中异动风控与机会识别系统的 JSON 判定器。\n"
    "你必须理解 A 股的分时交易、涨跌停、板块轮动和 T+1 特征。\n"
    "你只能根据输入数据判断，不能编造价格、公告、政策、资金流或新闻。\n"
    "规则引擎已经筛选出候选，你的任务不是重新扫描市场，而是判断：\n"
    "1. 信号是否真实；\n"
    "2. 是个股独立异动、板块共振、指数 Beta、政策驱动还是未知原因；\n"
    "3. 信号是否具有持续性；\n"
    "4. 是否存在追高、炸板、流动性或 T+1 风险；\n"
    "5. 是否值得向用户通知。\n"
    "不要输出绝对化的买入或卖出指令。不要使用“必涨”“必跌”“稳赚”等表达。只输出合法 JSON。"
)


def candidate_id(code: str, signal_type: str) -> str:
    """Stable identifier used to map batched verdicts back to candidates."""
    return f"{code}|{signal_type}"


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def parse_llm_json_response(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a (possibly fenced/malformed) LLM response into a dict."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        snippet = stripped[start:end + 1] if start >= 0 and end > start else stripped
        try:
            from json_repair import repair_json

            parsed = json.loads(repair_json(snippet))
        except Exception:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_llm_batch_results(text: Optional[str]) -> List[Dict[str, Any]]:
    """Parse a batched response into a list of per-candidate verdict dicts."""
    parsed = parse_llm_json_response(text)
    if isinstance(parsed, dict):
        results = parsed.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        return []
    return []


def normalize_verdict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clamp a single verdict's enum/range fields."""
    decision = str(raw.get("final_decision") or "").strip().lower()
    if decision not in _VALID_DECISIONS:
        decision = "ignore"
    direction = str(raw.get("direction") or "neutral").strip().lower()
    if direction not in _VALID_DIRECTIONS:
        direction = "neutral"
    driver = str(raw.get("driver_type") or "unknown").strip().lower()
    if driver not in _VALID_DRIVERS:
        driver = "unknown"
    quality = str(raw.get("signal_quality") or "low").strip().lower()
    if quality not in _VALID_QUALITY:
        quality = "low"
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "id": str(raw.get("id") or "").strip(),
        "final_decision": decision,
        "direction": direction,
        "need_notification": truthy(raw.get("need_notification")) and decision in {"watch", "risk"},
        "confidence": round(confidence, 4),
        "driver_type": driver,
        "signal_quality": quality,
        "summary": str(raw.get("summary") or "")[:300],
        "reason": str(raw.get("reason") or "")[:600],
        "risk": str(raw.get("risk") or "")[:400],
        "holder_suggestion": str(raw.get("holder_suggestion") or "")[:300],
        "observer_suggestion": str(raw.get("observer_suggestion") or "")[:300],
        "t1_warning": str(raw.get("t1_warning") or "")[:300],
        "invalidation": str(raw.get("invalidation") or "")[:300],
    }


def build_batch_prompt(
    candidates: Sequence[Dict[str, Any]],
    market_context: Dict[str, Any],
) -> str:
    payload = {
        "market_context": market_context,
        "candidates": list(candidates),
    }
    return (
        "下面是一批由规则引擎筛选出的 A 股盘中候选异动信号。市场上下文只在本批次开头给出一次。\n"
        "请逐个判断每个候选：信号是否真实、驱动类型、是否可持续、风险（含 T+1）、是否值得通知。\n"
        "由于 A 股股票存在 T+1 约束，新增仓位无法当日卖出，必须分别给出已持仓者与未持仓观察者的建议，"
        "且不得输出“立即买入”“追涨”“当日止损”等绝对化指令。\n"
        "只输出一个 JSON object，不要 markdown。顶层是 results 数组，每个元素必须原样回传输入里的 id 字段，格式：\n"
        "{\n"
        '  "results": [\n'
        "    {\n"
        '      "id": "600519|strong_to_weak_failure",\n'
        '      "final_decision": "watch|risk|ignore",\n'
        '      "direction": "bullish|bearish|neutral",\n'
        '      "need_notification": true,\n'
        '      "confidence": 0.82,\n'
        '      "driver_type": "stock_specific|sector|index_beta|policy|unknown",\n'
        '      "signal_quality": "high|medium|low",\n'
        '      "summary": "一句话摘要",\n'
        '      "reason": "判断依据",\n'
        '      "risk": "主要风险",\n'
        '      "holder_suggestion": "对已持仓者的观察建议",\n'
        '      "observer_suggestion": "对未持仓者的观察建议",\n'
        '      "t1_warning": "与 T+1 相关的风险提示",\n'
        '      "invalidation": "什么情况说明当前判断失效"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


class AShareIntradayLLMJudge:
    """Uses the configured LLM client to review batches of rule candidates."""

    def __init__(self, config: Any, *, client: Optional[LLMClient] = None) -> None:
        self.config = config
        self._client = client

    def _get_client(self) -> Optional[LLMClient]:
        if self._client is not None:
            return self._client
        try:
            self._client = LLMClient(config=self.config)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("初始化 A 股盘中 LLMClient 失败: %s", exc)
            return None
        return self._client

    def is_available(self) -> bool:
        client = self._get_client()
        try:
            return bool(client is not None and client.is_available())
        except Exception:
            return False

    def judge_batch(
        self,
        candidates: Sequence[Dict[str, Any]],
        market_context: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Judge candidates in one call; returns ``{candidate_id: verdict}``.

        Each candidate dict must carry an ``id`` field. Missing/invalid entries
        are simply absent from the result (callers fall back deterministically).
        """
        if not candidates:
            return {}
        client = self._get_client()
        if client is None or not self.is_available():
            logger.warning("LLM 未配置，跳过 A 股盘中候选批量判定（%s 个）", len(candidates))
            return {}

        valid_ids = {str(item.get("id")) for item in candidates}
        try:
            prompt = build_batch_prompt(candidates, market_context)
            max_tokens = min(8000, 700 * len(candidates) + 400)
            result = client.complete_json(
                LLMRequest(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=max_tokens,
                    timeout=LLM_TIMEOUT,
                    call_type="a_share_intraday_judge",
                )
            )
            results = parse_llm_batch_results(getattr(result, "text", None))
        except Exception as exc:
            logger.warning("A 股盘中 LLM 批量调用失败（%s 个候选）: %s", len(candidates), exc)
            return {}

        if not results:
            logger.warning("A 股盘中 LLM 批量返回无法解析（%s 个候选）", len(candidates))
            return {}

        candidate_ids = [str(item.get("id")) for item in candidates]
        verdicts: Dict[str, Dict[str, Any]] = {}
        for index, raw in enumerate(results):
            verdict = normalize_verdict(raw)
            rid = verdict["id"]
            if rid not in valid_ids and index < len(candidate_ids):
                # Fall back to positional mapping only when the id was dropped.
                rid = candidate_ids[index]
                verdict["id"] = rid
            if rid in valid_ids and rid not in verdicts:
                verdicts[rid] = verdict
        return verdicts
