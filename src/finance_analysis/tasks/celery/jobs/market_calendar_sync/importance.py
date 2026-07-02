# -*- coding: utf-8 -*-
"""LLM-based market importance scoring for finance calendar events."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from finance_analysis.core.time import utc_now
from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import MarketCalendarEventRepo
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.llm import LLMClient, LLMRequest
from finance_analysis.tasks.celery.jobs.us_intraday_analysis.llm import parse_llm_batch_results

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
DEFAULT_BATCH_SIZE = 10


@dataclass(frozen=True)
class EventCompanyContext:
    symbol: Optional[str]
    company_name: Optional[str]
    market_cap: Optional[float]
    current_price: Optional[float]


def _clean_text(value: Any, max_len: int = 300) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) > max_len:
        return text[:max_len].rstrip()
    return text


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _jsonable_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _event_payload(event: FinanceEvent, company_context: EventCompanyContext) -> Dict[str, Any]:
    return {
        "event_id": int(event.id),
        "event_key": event.event_key,
        "calendar_type": event.calendar_type,
        "market": event.market,
        "symbol": event.symbol,
        "counter_name": event.counter_name,
        "company_name": company_context.company_name or event.counter_name,
        "event_type": event.event_type,
        "activity_type": event.activity_type,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "event_datetime": _jsonable_datetime(event.event_datetime),
        "title": event.title,
        "content": event.content,
        "star": event.star,
        "provider_star": event.star,
        "data_kv_json": event.data_kv_json,
        "market_cap": company_context.market_cap,
        "current_price": company_context.current_price,
        "prompt_version": PROMPT_VERSION,
    }


def compute_importance_input_hash(event: FinanceEvent, company_context: EventCompanyContext) -> str:
    payload = {
        key: value
        for key, value in _event_payload(event, company_context).items()
        if key
        in {
            "event_key",
            "calendar_type",
            "symbol",
            "counter_name",
            "event_type",
            "activity_type",
            "event_date",
            "event_datetime",
            "title",
            "content",
            "star",
            "data_kv_json",
            "market_cap",
            "prompt_version",
        }
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def build_event_importance_prompt(events: Sequence[Dict[str, Any]]) -> str:
    payload = list(events)
    return (
        "你是美股财经日历事件的客观市场重要性评分器。\n\n"
        "评分目标：评估事件对整个美股市场、纳斯达克和标普等主要指数、重要行业和板块、"
        "大型上市公司、行业关键公司和周期风向标的潜在关注价值。评分是市场关注价值，不是涨跌方向。\n\n"
        "评分范围使用 1-10 分：\n"
        "10：可能影响整个市场、主要指数或全球风险偏好的核心事件。\n"
        "9：超大型公司、关键行业龙头、行业风向标的核心财报或重大事件。\n"
        "8：大型公司或重要板块公司的重要财报、指引及重大公司事件。\n"
        "7：具有明显行业影响力的公司事件。\n"
        "5-6：普通中型公司的财报或具有一定关注价值的事件。\n"
        "3-4：小型公司的常规财报、普通分红或普通公司行动。\n"
        "1-2：市场影响很小的例行事件、信息不足或普通小公司事件。\n\n"
        "公司规模原则：当提供 market_cap 时，将其作为美元市值理解并明确考虑公司规模。"
        "超大型及大型公司事件通常比小公司同类事件更重要，但公司规模不是唯一因素。"
        "即使市值不是最大，行业关键公司、周期风向标也可以获得高分。"
        "小公司不能仅因为事件类型是 earnings 就获得高分；普通小公司的常规财报原则上不应超过 5 分。"
        "市值缺失且公司影响力无法可靠判断时，应降低置信度。不得虚构公司规模、行业地位或市场份额。"
        "例如，存储芯片、半导体和 AI 基础设施等关键环节的行业风向标公司财报，"
        "可能显著高于陌生小公司的普通财报；但不要硬编码任何 symbol。\n\n"
        "事件类型原则：FOMC、CPI、PCE、非农、GDP、重大就业和通胀数据通常高分。"
        "大公司和行业龙头财报通常高分。财报指引、重大监管、重大并购等高于例行事件。"
        "普通分红通常低分。拆股本身通常不是基本面重大变化，除非公司规模和市场关注度很高。"
        "IPO 应结合发行规模、公司影响力和市场热度判断。仅凭标题无法判断时，保守评分。\n\n"
        "禁止事项：不预测涨跌；不输出 bullish/bearish；不给交易建议；"
        "不虚构新闻、市场预期或财报数据；不使用训练记忆中的具体实时市值替代输入数据；"
        "不因为股票位于用户 watch list 就提高客观市场重要性评分。watch list 属于个人相关性，"
        "本评分只评估客观市场重要性。\n\n"
        "只输出 JSON array，不要 Markdown，不要 JSON 之外的文字。格式如下：\n"
        "[\n"
        "  {\n"
        '    "event_id": 123,\n'
        '    "importance_score": 9,\n'
        '    "importance_reason": "该公司是行业重要风向标，财报可能影响相关板块预期。",\n'
        '    "confidence": 0.88\n'
        "  }\n"
        "]\n\n"
        f"待评分事件：\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
    )


def normalize_importance_results(
    raw_results: Sequence[Dict[str, Any]],
    expected_event_ids: Sequence[int],
) -> List[Dict[str, Any]]:
    expected = {int(event_id) for event_id in expected_event_ids}
    normalized: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw_results:
        event_id = _as_int(item.get("event_id"), 0)
        if event_id not in expected:
            logger.warning("财经日历重要性评分返回未知 event_id: %s", event_id)
            continue
        if event_id in seen:
            continue
        seen.add(event_id)
        normalized.append(
            {
                "event_id": event_id,
                "importance_score": int(_clamp(_as_int(item.get("importance_score"), 1), 1, 10)),
                "importance_reason": _clean_text(item.get("importance_reason") or item.get("reason"), 300),
                "confidence": _clamp(_as_float(item.get("confidence"), 0.0), 0.0, 1.0),
            }
        )
    return normalized


class MarketCalendarImportanceService:
    """Scores stored finance calendar events with the shared LLM client."""

    def __init__(
        self,
        *,
        repo: Optional[MarketCalendarEventRepo] = None,
        quote_fetcher: Optional[Any] = None,
        llm_client: Optional[LLMClient] = None,
        config: Optional[Any] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.repo = repo or MarketCalendarEventRepo()
        self.quote_fetcher = quote_fetcher or LongbridgeFetcher()
        self.llm_client = llm_client or LLMClient(config=config)
        self.batch_size = max(1, min(int(batch_size or DEFAULT_BATCH_SIZE), 20))
        self._quote_cache: Dict[str, EventCompanyContext] = {}

    def score_event_ids(self, event_ids: Sequence[int]) -> Dict[str, Any]:
        ids = list(dict.fromkeys(int(event_id) for event_id in event_ids if event_id is not None))
        if not ids:
            return {"requested": 0, "scored": 0, "skipped": 0, "errors": []}
        if not self.llm_client.is_available():
            logger.warning("LLM 未配置，跳过财经日历重要性评分")
            return {"requested": len(ids), "scored": 0, "skipped": len(ids), "errors": ["llm_unavailable"]}

        events = self.repo.list_events_by_ids(ids)
        prepared: List[Dict[str, Any]] = []
        skipped = 0
        for event in events:
            company_context = self._company_context(event)
            input_hash = compute_importance_input_hash(event, company_context)
            if (
                getattr(event, "importance_score", None) is not None
                and getattr(event, "importance_prompt_version", None) == PROMPT_VERSION
                and getattr(event, "importance_input_hash", None) == input_hash
            ):
                skipped += 1
                continue
            prepared.append(
                {
                    "event": event,
                    "company_context": company_context,
                    "input_hash": input_hash,
                    "prompt_payload": _event_payload(event, company_context),
                }
            )

        scored = 0
        errors: List[str] = []
        for batch in self._chunks(prepared, self.batch_size):
            try:
                scored += self._score_batch(batch)
            except Exception as exc:
                message = str(exc)
                logger.warning("财经日历重要性评分批次失败: %s", message, exc_info=True)
                errors.append(message)
        return {"requested": len(ids), "scored": scored, "skipped": skipped, "errors": errors}

    def _company_context(self, event: FinanceEvent) -> EventCompanyContext:
        symbol = str(getattr(event, "symbol", "") or "").strip().upper()
        if not symbol:
            return EventCompanyContext(
                symbol=None, company_name=getattr(event, "counter_name", None), market_cap=None, current_price=None
            )
        if symbol in self._quote_cache:
            return self._quote_cache[symbol]
        context = EventCompanyContext(
            symbol=symbol, company_name=getattr(event, "counter_name", None), market_cap=None, current_price=None
        )
        try:
            context_method = getattr(self.quote_fetcher, "get_company_quote_context", None)
            if callable(context_method):
                quote_context = context_method(symbol)
                if quote_context is not None:
                    context = EventCompanyContext(
                        symbol=symbol,
                        company_name=self._context_value(quote_context, "name") or getattr(event, "counter_name", None),
                        market_cap=self._context_value(quote_context, "total_mv"),
                        current_price=self._context_value(quote_context, "price"),
                    )
            else:
                quote = self.quote_fetcher.get_realtime_quote(symbol)
                if quote is not None:
                    context = EventCompanyContext(
                        symbol=symbol,
                        company_name=(getattr(quote, "name", None) or getattr(event, "counter_name", None)),
                        market_cap=getattr(quote, "total_mv", None),
                        current_price=getattr(quote, "price", None),
                    )
        except Exception as exc:
            logger.warning("获取财经日历评分市值上下文失败: symbol=%s error=%s", symbol, exc, exc_info=True)
        self._quote_cache[symbol] = context
        return context

    @staticmethod
    def _context_value(context: Any, key: str) -> Any:
        if isinstance(context, dict):
            return context.get(key)
        return getattr(context, key, None)

    def _score_batch(self, batch: Sequence[Dict[str, Any]]) -> int:
        if not batch:
            return 0
        prompt_payload = [item["prompt_payload"] for item in batch]
        result = self.llm_client.complete_json(
            LLMRequest(
                messages=[
                    {"role": "system", "content": "你是美股财经日历客观市场重要性 JSON 评分器，只输出 JSON。"},
                    {"role": "user", "content": build_event_importance_prompt(prompt_payload)},
                ],
                temperature=0.1,
                max_tokens=6000,
                call_type="market_calendar_importance",
            )
        )
        expected_ids = [int(item["event"].id) for item in batch]
        normalized = normalize_importance_results(parse_llm_batch_results(result.text), expected_ids)
        by_id = {int(item["event"].id): item for item in batch}
        scored_at = utc_now()
        updated = 0
        for item in normalized:
            event_id = int(item["event_id"])
            source = by_id.get(event_id)
            if source is None:
                continue
            if self.repo.update_importance_assessment(
                event_id,
                score=item["importance_score"],
                reason=item["importance_reason"],
                confidence=item["confidence"],
                model=result.model_used,
                prompt_version=PROMPT_VERSION,
                input_hash=source["input_hash"],
                scored_at=scored_at,
            ):
                updated += 1
        missed = set(expected_ids) - {int(item["event_id"]) for item in normalized}
        if missed:
            logger.warning("财经日历重要性评分遗漏事件: event_ids=%s", sorted(missed))
        return updated

    @staticmethod
    def _chunks(items: Sequence[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
        return [list(items[index:index + size]) for index in range(0, len(items), size)]
