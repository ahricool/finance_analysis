# -*- coding: utf-8 -*-
"""LLM prompts and response normalization for US premarket news intelligence."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from finance_analysis.llm import LLMClient, LLMRequest
from finance_analysis.tasks.celery.jobs.us_intraday_analysis.llm import parse_llm_batch_results

from .models import NewsCandidate

logger = logging.getLogger(__name__)

_EVENT_TYPES = {
    "earnings",
    "guidance",
    "analyst_rating",
    "product",
    "regulation",
    "macro",
    "mna",
    "legal",
    "other",
}
_TIME_SENSITIVITY = {"today", "this_week", "long_term"}
_IMPACTS = {"bullish", "bearish", "neutral", "mixed", "unclear"}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _clean_symbols(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    symbols: List[str] = []
    for item in value:
        text = str(item or "").strip().upper()
        if text:
            symbols.append(text.removesuffix(".US"))
    return list(dict.fromkeys(symbols))


def _clean_text(value: Any, max_len: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        return text[:max_len].rstrip()
    return text


def build_importance_prompt(candidates: Sequence[NewsCandidate]) -> str:
    payload = [candidate.to_prompt_dict() for candidate in candidates]
    return (
        "你是美股盘前新闻情报系统的第一阶段筛选器。请从候选新闻中筛选最多 10 条最重要新闻，"
        "合并重复或高度相似新闻，按市场重要性从高到低排序。\n\n"
        "排序规则：\n"
        "1. 直接影响营收、利润、指引、订单、监管、竞争格局的优先。\n"
        "2. 影响大市值科技股、半导体、AI 基础设施、云厂商的优先。\n"
        "3. 重复新闻合并，保留最有代表性的一条。\n"
        "4. 纯营销、软文、价格复述、无实质增量的新闻降低分数。\n\n"
        "只输出 JSON array，不要 markdown，不要解释 JSON 之外的文字。格式如下：\n"
        "[\n"
        "  {\n"
        '    "news_id_or_url": "...",\n'
        '    "title": "...",\n'
        '    "related_symbols": ["NVDA", "AMD"],\n'
        '    "importance_score": 8,\n'
        '    "importance_reason": "...",\n'
        '    "event_type": "earnings|guidance|analyst_rating|product|regulation|macro|mna|legal|other",\n'
        '    "time_sensitivity": "today|this_week|long_term",\n'
        '    "confidence": 0.8\n'
        "  }\n"
        "]\n\n"
        f"候选新闻：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_impact_prompt(selected: Sequence[Dict[str, Any]], candidates_by_key: Dict[str, NewsCandidate]) -> str:
    payload: List[Dict[str, Any]] = []
    for item in selected[:10]:
        key = str(item.get("news_id_or_url") or item.get("url") or "").strip()
        candidate = candidates_by_key.get(key)
        payload.append(
            {
                "news_id_or_url": key,
                "title": item.get("title") or (candidate.title if candidate else ""),
                "related_symbols": item.get("related_symbols") or (candidate.related_symbols if candidate else []),
                "importance_score": item.get("importance_score"),
                "importance_reason": item.get("importance_reason"),
                "description": candidate.description if candidate else "",
                "url": candidate.url if candidate else key,
            }
        )
    return (
        "你是美股盘前新闻情报系统的第二阶段影响方向判定器。请基于新闻标题、摘要和 URL，判断"
        "每条新闻对相关股票的可能影响方向。\n\n"
        "要求：\n"
        "1. 不允许给出确定性交易建议，不允许输出“必涨/必跌”。\n"
        "2. 必须区分短期情绪影响和中长期基本面影响。\n"
        "3. 信息不足时返回 unclear，不要编造。\n"
        "4. impact_score 范围为 -5 到 5，负数偏利空，正数偏利多。\n\n"
        "只输出 JSON array，不要 markdown，不要解释 JSON 之外的文字。格式如下：\n"
        "[\n"
        "  {\n"
        '    "news_id_or_url": "...",\n'
        '    "title": "...",\n'
        '    "related_symbols": ["NVDA"],\n'
        '    "impact": "bullish|bearish|neutral|mixed|unclear",\n'
        '    "impact_score": 2,\n'
        '    "confidence": 0.7,\n'
        '    "reason": "...",\n'
        '    "watch_points": ["..."],\n'
        '    "risk_notes": ["..."]\n'
        "  }\n"
        "]\n\n"
        f"待判断新闻：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def normalize_importance_results(raw_results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_results:
        key = _clean_text(item.get("news_id_or_url") or item.get("url"), 1000)
        if not key or key in seen:
            continue
        seen.add(key)
        event_type = str(item.get("event_type") or "other").strip().lower()
        time_sensitivity = str(item.get("time_sensitivity") or "this_week").strip().lower()
        normalized.append(
            {
                "news_id_or_url": key,
                "title": _clean_text(item.get("title"), 300),
                "related_symbols": _clean_symbols(item.get("related_symbols")),
                "importance_score": _clamp(_as_int(item.get("importance_score"), 1), 1, 10),
                "importance_reason": _clean_text(item.get("importance_reason"), 1000),
                "event_type": event_type if event_type in _EVENT_TYPES else "other",
                "time_sensitivity": (
                    time_sensitivity if time_sensitivity in _TIME_SENSITIVITY else "this_week"
                ),
                "confidence": _clamp(_as_float(item.get("confidence"), 0), 0, 1),
            }
        )
        if len(normalized) >= 10:
            break
    normalized.sort(key=lambda item: item["importance_score"], reverse=True)
    return normalized[:10]


def normalize_impact_results(raw_results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_results:
        key = _clean_text(item.get("news_id_or_url") or item.get("url"), 1000)
        if not key or key in seen:
            continue
        seen.add(key)
        impact = str(item.get("impact") or "unclear").strip().lower()
        watch_points = item.get("watch_points")
        risk_notes = item.get("risk_notes")
        normalized.append(
            {
                "news_id_or_url": key,
                "title": _clean_text(item.get("title"), 300),
                "related_symbols": _clean_symbols(item.get("related_symbols")),
                "impact": impact if impact in _IMPACTS else "unclear",
                "impact_score": _clamp(_as_int(item.get("impact_score"), 0), -5, 5),
                "confidence": _clamp(_as_float(item.get("confidence"), 0), 0, 1),
                "reason": _clean_text(item.get("reason"), 1200),
                "watch_points": [
                    _clean_text(text, 300) for text in (watch_points if isinstance(watch_points, list) else [])
                ][:5],
                "risk_notes": [
                    _clean_text(text, 300) for text in (risk_notes if isinstance(risk_notes, list) else [])
                ][:5],
            }
        )
        if len(normalized) >= 10:
            break
    return normalized


class PremarketNewsLLMAnalyzer:
    """Runs the two-stage LLM analysis for premarket news."""

    def __init__(self, config: Any) -> None:
        self.config = config

    def select_important_news(self, candidates: Sequence[NewsCandidate]) -> List[Dict[str, Any]]:
        if not candidates:
            return []
        try:
            client = LLMClient(config=self.config)
            if not client.is_available():
                logger.warning("LLM 未配置，跳过美股盘前新闻重要性筛选")
                return []
            result = client.complete_json(
                LLMRequest(
                    messages=[
                        {"role": "system", "content": "你是美股盘前新闻重要性筛选器，只输出 JSON。"},
                        {"role": "user", "content": build_importance_prompt(candidates)},
                    ],
                    temperature=0.1,
                    max_tokens=5000,
                    call_type="us_premarket_news_importance",
                )
            )
            return normalize_importance_results(parse_llm_batch_results(result.text))
        except Exception as exc:
            logger.warning("美股盘前新闻重要性筛选失败: %s", exc)
            return []

    def judge_impact(
        self,
        selected_news: Sequence[Dict[str, Any]],
        candidates_by_key: Dict[str, NewsCandidate],
    ) -> List[Dict[str, Any]]:
        if not selected_news:
            return []
        try:
            client = LLMClient(config=self.config)
            if not client.is_available():
                logger.warning("LLM 未配置，跳过美股盘前新闻影响方向判断")
                return []
            result = client.complete_json(
                LLMRequest(
                    messages=[
                        {"role": "system", "content": "你是美股盘前新闻影响方向 JSON 判定器，只输出 JSON。"},
                        {"role": "user", "content": build_impact_prompt(selected_news, candidates_by_key)},
                    ],
                    temperature=0.1,
                    max_tokens=6000,
                    call_type="us_premarket_news_impact",
                )
            )
            return normalize_impact_results(parse_llm_batch_results(result.text))
        except Exception as exc:
            logger.warning("美股盘前新闻影响方向判断失败: %s", exc)
            return []
