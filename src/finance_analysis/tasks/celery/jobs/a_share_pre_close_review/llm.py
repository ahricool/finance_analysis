"""Bounded Web LLM research and validated portfolio decision output."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional, Sequence

from finance_analysis.llm import LLMClient, LLMRequest

from ..a_share_intraday_analysis.llm import parse_llm_json_response
from .config import ALLOWED_HOLDING_ACTIONS, PreCloseReviewConfig
from .models import DataQuality, SecurityReview

logger = logging.getLogger(__name__)

_SHARE_COUNT_PATTERN = re.compile(r"(?:\d+(?:\.\d+)?\s*股|\d+(?:\.\d+)?\s*shares?)", re.IGNORECASE)


class ASharePreCloseWebLLM:
    """Uses the repository's ``llm_web`` channel only after deterministic screening."""

    def __init__(
        self,
        config: Any,
        limits: PreCloseReviewConfig,
        *,
        client: Optional[LLMClient] = None,
    ) -> None:
        self.config = config
        self.limits = limits
        self.client = client
        self.call_count = 0

    def research_news(
        self,
        entities: Sequence[dict[str, Any]],
        existing_news: Sequence[dict[str, Any]],
        *,
        trading_date: str,
        warnings: list[str],
        deadline: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        bounded = list(entities[: self.limits.max_news_entities])
        if not bounded:
            return []
        entity_keys = {item["key"] for item in bounded}
        payload = {
            "trading_date": trading_date,
            "entities": bounded,
            "existing_recent_news": [item for item in existing_news if item.get("entity_key") in entity_keys][:20],
        }
        parsed = self._complete_json(
            system=(
                "你是 A 股收盘前新闻研究员。使用 Web 搜索核对输入实体最近 7 天的重要新闻、公告、政策和风险。"
                "只研究输入实体，不扩展全市场扫描；不得编造行情、新闻、来源或 URL。只输出 JSON。"
            ),
            user=(
                "按 entity_key 返回 items 数组。每项包含 entity_key、summary、impact(bullish/bearish/neutral/unknown)、"
                "coverage(complete/partial/none)、sources；sources 最多 3 条，每条仅含 title、url、published_at。\n"
                f"输入：{json.dumps(payload, ensure_ascii=False)}"
            ),
            call_type="a_share_pre_close_news",
            warnings=warnings,
            deadline=deadline,
        )
        results = self._validate_news_items(parsed, bounded) if parsed is not None else []
        if not results:
            warnings.append("Web LLM 新闻研究不可用或无结果，最终判断不使用未核实新闻")
        return results

    def decide(
        self,
        context: dict[str, Any],
        holdings: Sequence[SecurityReview],
        candidates: Sequence[SecurityReview],
        data_quality: DataQuality,
        *,
        warnings: list[str],
        deadline: Optional[float] = None,
    ) -> tuple[dict[str, Any], bool]:
        parsed = self._complete_json(
            system=(
                "你是谨慎的 A 股收盘前组合复核器。程序已经完成行情扫描和新闻研究；你不能重新扫描市场，"
                "不能创造价格、资金流、新闻、账户总仓位、现金比例或购买力。只输出 JSON。"
                "持仓建议必须按当前单只持仓比例表达，不得给具体股数。数据不足时只能维持或观察。"
            ),
            user=self._decision_prompt(context),
            call_type="a_share_pre_close_decision",
            warnings=warnings,
            deadline=deadline,
        )
        if parsed is None:
            warnings.append("最终 Web LLM 判断不可用，已生成确定性降级建议")
            return fallback_decision(context, holdings, candidates, data_quality), True
        validated = validate_decision(parsed, context, holdings, candidates, data_quality)
        if validated is None:
            warnings.append("最终 Web LLM 返回格式不合规，已生成确定性降级建议")
            return fallback_decision(context, holdings, candidates, data_quality), True
        return validated, False

    def _complete_json(
        self,
        *,
        system: str,
        user: str,
        call_type: str,
        warnings: list[str],
        deadline: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        client = self._get_client()
        if client is None:
            return None
        for attempt in range(self.limits.web_llm_attempts):
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                warnings.append(f"{call_type} 未执行或停止重试: 任务时间预算已耗尽")
                return None
            timeout = float(self.limits.web_llm_timeout_seconds)
            if remaining is not None:
                timeout = min(timeout, max(1.0, remaining))
            try:
                self.call_count += 1
                result = client.complete_json(
                    LLMRequest(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        provider="llm_web",
                        temperature=0.1,
                        max_tokens=6000,
                        timeout=timeout,
                        call_type=call_type,
                    )
                )
                parsed = parse_llm_json_response(getattr(result, "text", None))
                if parsed is not None:
                    return parsed
                raise ValueError("LLM response is not a JSON object")
            except Exception as exc:
                logger.warning("%s Web LLM 调用失败 attempt=%s: %s", call_type, attempt + 1, exc)
                if attempt + 1 == self.limits.web_llm_attempts:
                    warnings.append(f"{call_type} 调用失败: {str(exc)[:160]}")
        return None

    def _get_client(self) -> Optional[LLMClient]:
        if self.client is not None:
            return self.client
        try:
            self.client = LLMClient(config=self.config)
            return self.client
        except Exception as exc:
            logger.warning("初始化 A 股收盘前 Web LLM 失败: %s", exc)
            return None

    def _validate_news_items(
        self,
        parsed: dict[str, Any],
        entities: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        valid_keys = {str(item.get("key")) for item in entities}
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in parsed.get("items", []) if isinstance(parsed.get("items"), list) else []:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("entity_key") or "")
            if key not in valid_keys or key in seen:
                continue
            seen.add(key)
            impact = str(raw.get("impact") or "unknown").lower()
            coverage = str(raw.get("coverage") or "none").lower()
            sources = []
            for source in raw.get("sources", []) if isinstance(raw.get("sources"), list) else []:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url") or "").strip()
                if not url.startswith(("http://", "https://")):
                    continue
                sources.append(
                    {
                        "title": clean_text(source.get("title"), 160),
                        "url": url[:500],
                        "published_at": clean_text(source.get("published_at"), 40),
                    }
                )
            output.append(
                {
                    "entity_key": key,
                    "summary": clean_text(raw.get("summary"), 500),
                    "impact": impact if impact in {"bullish", "bearish", "neutral", "unknown"} else "unknown",
                    "coverage": coverage if coverage in {"complete", "partial", "none"} else "none",
                    "sources": sources[: self.limits.max_news_items_per_entity],
                }
            )
        return output

    @staticmethod
    def _decision_prompt(context: dict[str, Any]) -> str:
        return (
            "基于以下结构化上下文输出一个 JSON object，字段为：\n"
            "market_summary: {state, conclusion, rationale[]}；\n"
            "sector_views: [{name, continuity, rationale}]；\n"
            "risks: [string]；\n"
            "holdings: [{code, action, percent_min, percent_max, condition, rationale, invalidation}]；\n"
            "candidates: [{code, rationale, condition, invalidation}]；\n"
            "invalidation_conditions: [string]；confidence: high/medium/low；data_note: string。\n"
            "action 仅可为 maintain/watch/reduce/add_on_condition/exit_or_large_reduce。"
            "reduce 建议 10%-50%，add_on_condition 建议 5%-30%，exit_or_large_reduce 建议 50%-100%；"
            "maintain/watch 不填写比例。所有比例均指该股票当前持仓，不是账户总仓位。\n"
            f"输入：{json.dumps(context, ensure_ascii=False)}"
        )


def validate_decision(
    raw: dict[str, Any],
    context: dict[str, Any],
    holdings: Sequence[SecurityReview],
    candidates: Sequence[SecurityReview],
    quality: DataQuality,
) -> Optional[dict[str, Any]]:
    if not isinstance(raw.get("holdings"), list):
        return None
    raw_by_code = {str(item.get("code") or ""): item for item in raw["holdings"] if isinstance(item, dict)}
    holding_advice = []
    for holding in holdings:
        item = raw_by_code.get(holding.code, {})
        action = str(item.get("action") or "watch").lower()
        if action not in ALLOWED_HOLDING_ACTIONS:
            action = "watch"
        if not quality.sufficient_for_active_advice or not holding.data_complete:
            action = "watch" if holding.change_pct is not None else "maintain"
        condition = clean_text(item.get("condition"), 240)
        if action == "add_on_condition" and not condition:
            action = "watch"
        percent_min, percent_max = normalize_percent_range(action, item)
        holding_advice.append(
            {
                "code": holding.code,
                "name": holding.name,
                "action": action,
                "percent_min": percent_min,
                "percent_max": percent_max,
                "condition": condition,
                "rationale": clean_text(item.get("rationale"), 400),
                "invalidation": clean_text(item.get("invalidation"), 240),
            }
        )

    valid_candidates = {item.code: item for item in candidates}
    candidate_advice = []
    if quality.sufficient_for_active_advice:
        for item in raw.get("candidates", []) if isinstance(raw.get("candidates"), list) else []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "")
            if code not in valid_candidates:
                continue
            candidate_advice.append(
                {
                    "code": code,
                    "name": valid_candidates[code].name,
                    "action": "watch",
                    "rationale": clean_text(item.get("rationale"), 320),
                    "condition": clean_text(item.get("condition"), 240),
                    "invalidation": clean_text(item.get("invalidation"), 240),
                }
            )

    deterministic_state = str(context.get("market", {}).get("state") or "unknown")
    market_summary = raw.get("market_summary") if isinstance(raw.get("market_summary"), dict) else {}
    confidence = str(raw.get("confidence") or quality.confidence).lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = quality.confidence
    if not quality.sufficient_for_active_advice:
        confidence = "low"
    return {
        "market_summary": {
            "state": deterministic_state,
            "conclusion": clean_text(market_summary.get("conclusion"), 400),
            "rationale": clean_string_list(market_summary.get("rationale"), 8, 240),
        },
        "sector_views": validate_sector_views(raw.get("sector_views"), context),
        "risks": clean_string_list(raw.get("risks"), 8, 260),
        "holdings": holding_advice,
        "candidates": candidate_advice,
        "invalidation_conditions": clean_string_list(raw.get("invalidation_conditions"), 8, 260),
        "confidence": confidence,
        "data_note": clean_text(raw.get("data_note"), 400),
    }


def fallback_decision(
    context: dict[str, Any],
    holdings: Sequence[SecurityReview],
    candidates: Sequence[SecurityReview],
    quality: DataQuality,
) -> dict[str, Any]:
    holding_advice = []
    for holding in holdings:
        action = "watch" if holding.change_pct is not None else "maintain"
        holding_advice.append(
            {
                "code": holding.code,
                "name": holding.name,
                "action": action,
                "percent_min": None,
                "percent_max": None,
                "condition": "等待行情、板块与新闻信息完整后再评估主动调整",
                "rationale": "Web LLM 不可用，采用保守确定性降级",
                "invalidation": "数据恢复后需重新复核",
            }
        )
    return {
        "market_summary": {
            "state": context.get("market", {}).get("state", "unknown"),
            "conclusion": "依据确定性行情指标完成收盘前复核，未形成高置信度主动调整结论。",
            "rationale": list(context.get("market", {}).get("rationale", []))[:8],
        },
        "sector_views": [
            {
                "name": item.get("name"),
                "continuity": item.get("continuity"),
                "rationale": item.get("rationale"),
            }
            for item in context.get("strong_sectors", [])[:5]
        ],
        "risks": ["Web 新闻或最终决策能力不可用，避免据此作主动加减仓判断"],
        "holdings": holding_advice,
        "candidates": [],
        "invalidation_conditions": ["行情数据、新闻覆盖或最终模型判断恢复后，应重新复核当前结论"],
        "confidence": "low" if not quality.sufficient_for_active_advice else "medium",
        "data_note": "确定性降级结果；仅提供维持或观察建议。",
    }


def normalize_percent_range(action: str, item: dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    ranges = {
        "reduce": (10, 50),
        "add_on_condition": (5, 30),
        "exit_or_large_reduce": (50, 100),
    }
    if action not in ranges:
        return None, None
    lower, upper = ranges[action]
    try:
        minimum = int(float(item.get("percent_min")))
        maximum = int(float(item.get("percent_max")))
    except (TypeError, ValueError):
        return lower, upper
    minimum = max(lower, min(upper, minimum))
    maximum = max(minimum, min(upper, maximum))
    return minimum, maximum


def validate_sector_views(raw: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    valid = {str(item.get("name")): item for item in context.get("strong_sectors", [])}
    output = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name not in valid:
            continue
        output.append(
            {
                "name": name,
                "continuity": valid[name].get("continuity"),
                "rationale": clean_text(item.get("rationale"), 320) or valid[name].get("rationale", ""),
            }
        )
    return output or [
        {
            "name": name,
            "continuity": item.get("continuity"),
            "rationale": item.get("rationale", ""),
        }
        for name, item in list(valid.items())[:5]
    ]


def clean_string_list(value: Any, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value[:limit] if (text := clean_text(item, item_limit))]


def clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if _SHARE_COUNT_PATTERN.search(text):
        return "建议按比例管理当前持仓，不提供具体买卖股数。"
    return text[:limit]


__all__ = ["ASharePreCloseWebLLM", "fallback_decision", "validate_decision"]
