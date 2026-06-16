# -*- coding: utf-8 -*-
"""LLM prompt construction, response parsing, and candidate judging."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from src.llm import LLMClient, LLMRequest

from .bars import aggregate_bars

logger = logging.getLogger(__name__)


def candidate_id(symbol: str, signal_type: str) -> str:
    """Stable identifier used to map batched LLM verdicts back to candidates."""
    return f"{symbol}|{signal_type}"


def build_intraday_llm_prompt(
    symbol: str,
    signal_type: str,
    metrics: Dict[str, Any],
    raw_context: Dict[str, Any],
) -> str:
    """Build the Chinese analyst prompt asking for a JSON-only verdict."""
    payload = {
        "symbol": symbol,
        "signal_type": signal_type,
        "metrics": metrics,
        "raw_context": raw_context,
    }
    return (
        "你是美股盘中异动提醒系统的分析员。请基于输入的实时行情、1分钟K线聚合指标、"
        "相对 QQQ/SOXX/UFO 的强弱关系，判断这个信号是否真的值得关注。\n\n"
        "重点回答：\n"
        "1. 这个信号是真突破/反转/失效，还是普通波动？\n"
        "2. 是个股自身强，还是被 QQQ、SOXX、UFO 等板块/大盘带动？\n"
        "3. 当前追高或追空风险大不大？\n"
        "4. 是否值得发通知？\n\n"
        "只输出一个 JSON object，不要 markdown，不要解释 JSON 之外的文字。格式如下：\n"
        "{\n"
        '  "final_decision": "watch|ignore|risk",\n'
        '  "need_notification": true,\n'
        '  "confidence": 0.76,\n'
        '  "summary": "一句话摘要",\n'
        '  "reason": "为什么这不是普通波动/或者为什么只是普通波动",\n'
        '  "risk": "追高/失效/回落风险",\n'
        '  "suggestion": "观察或处理建议"\n'
        "}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_intraday_batch_llm_prompt(
    candidates: Sequence[Dict[str, Any]],
    market_context: Dict[str, Dict[str, Any]],
) -> str:
    """Build a prompt that judges multiple candidates in a single request.

    ``candidates`` is a list of dicts shaped like
    ``{"id", "symbol", "signal_type", "metrics", "raw_context"}``. The model is
    asked to return one verdict per candidate, echoing back the ``id`` so each
    result can be mapped to its source candidate.
    """
    payload = {
        "market_context": market_context,
        "candidates": [
            {
                "id": item["id"],
                "symbol": item["symbol"],
                "signal_type": item["signal_type"],
                "metrics": item["metrics"],
                "raw_context": item["raw_context"],
            }
            for item in candidates
        ],
    }
    return (
        "你是美股盘中异动提醒系统的分析员。下面是一批候选异动信号，每个信号包含实时行情、"
        "1分钟K线聚合指标，以及相对 QQQ/SOXX/UFO 等板块的强弱关系。请逐个判断每个信号是否真的值得关注。\n\n"
        "对每个候选信号回答：\n"
        "1. 这个信号是真突破/反转/失效，还是普通波动？\n"
        "2. 是个股自身强，还是被 QQQ、SOXX、UFO 等板块/大盘带动？\n"
        "3. 当前追高或追空风险大不大？\n"
        "4. 是否值得发通知？\n\n"
        "只输出一个 JSON object，不要 markdown，不要解释 JSON 之外的文字。\n"
        "顶层是 results 数组，数组每个元素对应一个候选信号，必须原样回传输入里的 id 字段。格式如下：\n"
        "{\n"
        '  "results": [\n'
        "    {\n"
        '      "id": "NVDA|relative_strength_breakout",\n'
        '      "final_decision": "watch|ignore|risk",\n'
        '      "need_notification": true,\n'
        '      "confidence": 0.76,\n'
        '      "summary": "一句话摘要",\n'
        '      "reason": "为什么这不是普通波动/或者为什么只是普通波动",\n'
        '      "risk": "追高/失效/回落风险",\n'
        '      "suggestion": "观察或处理建议"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_llm_json_response(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a (possibly fenced or malformed) LLM response into a dict."""
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
    """Parse a batched response into a list of per-candidate verdict dicts.

    Accepts either ``{"results": [...]}`` or a bare JSON array, and tolerates
    fenced/malformed output via :func:`parse_llm_json_response`'s repair path.
    """
    parsed = parse_llm_json_response(text)
    if isinstance(parsed, dict):
        results = parsed.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        return []

    # ``parse_llm_json_response`` only returns dicts; retry for a bare array.
    if not text:
        return []
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("[")
        end = stripped.rfind("]")
        snippet = stripped[start:end + 1] if start >= 0 and end > start else stripped
        try:
            from json_repair import repair_json

            loaded = json.loads(repair_json(snippet))
        except Exception:
            return []
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    return []


def truthy(value: Any) -> bool:
    """Interpret loosely-typed LLM boolean values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


class IntradayLLMJudge:
    """Uses the configured LLM client to score a single signal candidate."""

    def __init__(self, config: Any) -> None:
        self.config = config

    def judge_batch(
        self,
        candidates: Sequence[Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Judge a batch of candidates in one LLM call.

        ``candidates`` is a list of dicts shaped like
        ``{"symbol", "signal_type", "metrics", "bars_1m"}``. Returns a mapping
        from :func:`candidate_id` to the parsed verdict; missing/invalid entries
        are simply absent from the result.
        """
        if not candidates:
            return {}
        try:
            client = LLMClient(config=self.config)
            if not client.is_available():
                logger.warning("LLM 未配置，跳过美股盘中候选信号批量判定（%s 个）", len(candidates))
                return {}

            prompt_items = [
                {
                    "id": candidate_id(item["symbol"], item["signal_type"]),
                    "symbol": item["symbol"],
                    "signal_type": item["signal_type"],
                    "metrics": item["metrics"],
                    "raw_context": self._build_raw_context(item["bars_1m"]),
                }
                for item in candidates
            ]
            prompt = build_intraday_batch_llm_prompt(prompt_items, market_context)
            max_tokens = min(8000, 700 * len(candidates) + 300)
            result = client.complete_json(
                LLMRequest(
                    messages=[
                        {"role": "system", "content": "你是美股盘中异动提醒系统的 JSON 判定器，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=max_tokens,
                    call_type="intraday_judge",
                )
            )

            results = parse_llm_batch_results(result.text)
            if not results:
                logger.warning("美股盘中 LLM 批量返回无法解析（%s 个候选）", len(candidates))
                return {}

            valid_ids = {item["id"] for item in prompt_items}
            verdicts: Dict[str, Dict[str, Any]] = {}
            for index, result in enumerate(results):
                rid = str(result.get("id") or "").strip()
                if rid not in valid_ids and index < len(prompt_items):
                    # Fall back to positional mapping when the model drops the id.
                    rid = prompt_items[index]["id"]
                if rid in valid_ids:
                    verdicts[rid] = result
            return verdicts
        except Exception as exc:
            logger.warning("美股盘中 LLM 批量调用失败（%s 个候选）: %s", len(candidates), exc)
            return {}

    @staticmethod
    def _build_raw_context(bars_1m: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "bars_1m_tail": list(bars_1m[-30:]),
            "bars_5m_tail": aggregate_bars(bars_1m, 5)[-12:],
            "bars_15m_tail": aggregate_bars(bars_1m, 15)[-8:],
        }

    def judge(
        self,
        symbol: str,
        signal_type: str,
        metrics: Dict[str, Any],
        bars_1m: Sequence[Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return the parsed LLM verdict, or ``None`` when unavailable/invalid."""
        try:
            client = LLMClient(config=self.config)
            if not client.is_available():
                logger.warning("LLM 未配置，跳过美股盘中候选信号判定: %s %s", symbol, signal_type)
                return None
            prompt = build_intraday_llm_prompt(
                symbol,
                signal_type,
                metrics,
                {
                    "bars_1m_tail": list(bars_1m[-30:]),
                    "bars_5m_tail": aggregate_bars(bars_1m, 5)[-12:],
                    "bars_15m_tail": aggregate_bars(bars_1m, 15)[-8:],
                    "market_context": market_context,
                },
            )
            result = client.complete_json(
                LLMRequest(
                    messages=[
                        {"role": "system", "content": "你是美股盘中异动提醒系统的 JSON 判定器，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=1200,
                    call_type="intraday_judge",
                    stock_code=symbol,
                )
            )
            parsed = parse_llm_json_response(result.text)
            if parsed is None:
                logger.warning("美股盘中 LLM 返回无法解析: %s %s", symbol, signal_type)
                return None
            return parsed
        except Exception as exc:
            logger.warning("美股盘中 LLM 调用失败 %s %s: %s", symbol, signal_type, exc)
            return None
