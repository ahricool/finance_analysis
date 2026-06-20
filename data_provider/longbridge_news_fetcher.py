# -*- coding: utf-8 -*-
"""
LongbridgeNewsFetcher - 长桥 OpenAPI 新闻获取

数据来源：长桥 Content API (GET /v1/content/{symbol}/news)
文档：https://open.longbridge.com/docs/content/news.md

去重策略（写入 news_intel 表）：
1. 主键：URL 唯一约束（Longbridge 返回稳定 url，缺失时用 news id 构造 canonical url）
2. 兜底：title + source + published_date 生成 hash 键（复用 DatabaseManager.save_news_intel）
3. 重复命中时更新 fetched_at，便于追踪最近抓取时间
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from data_provider.longbridge_fetcher import (
    LongbridgeFetcher,
    _longbridge_config_kwargs,
    _sanitize_longbridge_env,
    _to_longbridge_symbol,
)
from src.logging_config import log_external_call_exception
from src.search.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)

LONGBRIDGE_NEWS_SOURCE = "longbridge"
LONGBRIDGE_NEWS_CANONICAL_URL = "https://longbridge.com/news/{news_id}"


@dataclass(frozen=True)
class LongbridgeNewsRecord:
    """Normalized Longbridge news item for persistence and LLM context."""

    news_id: str
    title: str
    description: str
    url: str
    published_at: Optional[datetime]
    comments_count: int = 0
    likes_count: int = 0
    shares_count: int = 0

    def to_llm_dict(self) -> Dict[str, Any]:
        return {
            "id": self.news_id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


def _parse_published_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        ts = int(float(text))
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _canonical_news_url(news_id: str, url: str) -> str:
    cleaned = (url or "").strip()
    if cleaned:
        return cleaned
    news_id = (news_id or "").strip()
    if news_id:
        return LONGBRIDGE_NEWS_CANONICAL_URL.format(news_id=news_id)
    return ""


def _normalize_news_item(item: Any) -> Optional[LongbridgeNewsRecord]:
    news_id = str(getattr(item, "id", "") or "").strip()
    title = str(getattr(item, "title", "") or "").strip()
    description = str(getattr(item, "description", "") or "").strip()
    url = _canonical_news_url(news_id, str(getattr(item, "url", "") or ""))
    if not title and not url:
        return None
    return LongbridgeNewsRecord(
        news_id=news_id,
        title=title,
        description=description,
        url=url,
        published_at=_parse_published_at(getattr(item, "published_at", None)),
        comments_count=int(getattr(item, "comments_count", 0) or 0),
        likes_count=int(getattr(item, "likes_count", 0) or 0),
        shares_count=int(getattr(item, "shares_count", 0) or 0),
    )


def news_records_to_search_response(
    stock_code: str,
    records: Sequence[LongbridgeNewsRecord],
) -> SearchResponse:
    results = [
        SearchResult(
            title=record.title,
            snippet=record.description,
            url=record.url,
            source=LONGBRIDGE_NEWS_SOURCE,
            published_date=record.published_at.isoformat() if record.published_at else None,
        )
        for record in records
        if record.title or record.url
    ]
    return SearchResponse(
        query=f"{stock_code} longbridge news",
        results=results,
        provider=LONGBRIDGE_NEWS_SOURCE,
        success=True,
    )


class LongbridgeNewsFetcher:
    """Fetch security news from Longbridge Content API and persist with dedup."""

    _CONNECTION_ERRORS = ("client is closed", "context closed", "connection closed")

    def __init__(self, quote_fetcher: Optional[LongbridgeFetcher] = None) -> None:
        self._quote_fetcher = quote_fetcher or LongbridgeFetcher()
        self._ctx = None
        self._config = None
        self._ctx_lock = threading.Lock()
        self._cooldown_until = 0.0

    def is_available(self) -> bool:
        if not self._quote_fetcher._is_available():
            return False
        if self._cooldown_until > time.time():
            return False
        if self._cooldown_until:
            self._cooldown_until = 0.0
        return True

    def _is_connection_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(token in msg for token in self._CONNECTION_ERRORS)

    def _invalidate_ctx(self) -> None:
        with self._ctx_lock:
            self._ctx = None
            self._config = None

    def _mark_connection_cooldown(self, exc: Exception) -> None:
        self._invalidate_ctx()
        self._cooldown_until = time.time() + 15
        logger.warning("[LongbridgeNews] 连接异常，进入冷却: %s", exc)

    def _build_config(self):
        if self._config is not None:
            return self._config

        # Reuse quote fetcher credentials/config when already initialized.
        self._quote_fetcher._get_ctx()
        lb_config = getattr(self._quote_fetcher, "_config", None)
        if lb_config is not None:
            self._config = lb_config
            return lb_config

        from longbridge.openapi import Config

        _sanitize_longbridge_env()
        extra_kw = _longbridge_config_kwargs()
        for factory_name in ("from_apikey_env", "from_env"):
            factory = getattr(Config, factory_name, None)
            if factory is None:
                continue
            try:
                lb_config = factory()
                self._config = lb_config
                return lb_config
            except Exception as exc:
                logger.debug("[LongbridgeNews] Config.%s() 失败: %s", factory_name, exc)

        try:
            from data_provider.config import get_data_provider_config

            app_config = get_data_provider_config()
            lb_config = Config.from_apikey(
                app_config.longbridge_app_key,
                app_config.longbridge_app_secret,
                app_config.longbridge_access_token,
                **extra_kw,
            )
        except Exception:
            import os

            lb_config = Config.from_apikey(
                os.getenv("LONGBRIDGE_APP_KEY"),
                os.getenv("LONGBRIDGE_APP_SECRET"),
                os.getenv("LONGBRIDGE_ACCESS_TOKEN"),
                **extra_kw,
            )

        self._config = lb_config
        return lb_config

    def _get_ctx(self):
        if self._ctx is not None:
            return self._ctx
        with self._ctx_lock:
            if self._ctx is not None:
                return self._ctx
            if not self.is_available():
                return None
            try:
                from longbridge.openapi import ContentContext

                lb_config = self._build_config()
                if lb_config is None:
                    return None
                self._ctx = ContentContext(lb_config)
                logger.info("[LongbridgeNews] ContentContext 初始化成功")
                return self._ctx
            except Exception as exc:
                log_external_call_exception(
                    logger,
                    provider="longbridge",
                    operation="ContentContext",
                    exc=exc,
                )
                return None

    def fetch_news(
        self,
        stock_code: str,
        *,
        limit: Optional[int] = None,
    ) -> List[LongbridgeNewsRecord]:
        """Fetch normalized news records for a stock or index symbol."""
        if not self.is_available():
            return []

        symbol = _to_longbridge_symbol(stock_code)
        if symbol is None:
            logger.debug("[LongbridgeNews] 无法转换代码: %s", stock_code)
            return []

        ctx = self._get_ctx()
        if ctx is None:
            return []

        api_start = time.time()
        try:
            raw_items = ctx.news(symbol) or []
        except Exception as exc:
            log_external_call_exception(
                logger,
                provider="longbridge",
                operation="news",
                exc=exc,
                symbol=symbol,
                params={"symbol": symbol},
                elapsed=time.time() - api_start,
            )
            if self._is_connection_error(exc):
                self._mark_connection_cooldown(exc)
            return []

        records: List[LongbridgeNewsRecord] = []
        for raw in raw_items:
            normalized = _normalize_news_item(raw)
            if normalized is not None:
                records.append(normalized)

        if limit is not None and limit > 0:
            records = records[:limit]

        logger.info("[LongbridgeNews] %s 获取新闻 %s 条", symbol, len(records))
        return records

    def fetch_and_save_news(
        self,
        stock_code: str,
        *,
        name: str = "",
        dimension: str = "intraday_news",
        query_id: str = "",
        limit: Optional[int] = None,
    ) -> List[LongbridgeNewsRecord]:
        """Fetch news, persist with dedup, and return normalized records."""
        records = self.fetch_news(stock_code, limit=limit)
        if not records:
            return []

        try:
            from src.storage import DatabaseManager

            response = news_records_to_search_response(stock_code, records)
            DatabaseManager.get_instance().save_news_intel(
                code=stock_code,
                name=name,
                dimension=dimension,
                query=response.query,
                response=response,
                query_context={
                    "query_id": query_id,
                    "query_source": "system",
                },
            )
        except Exception as exc:
            logger.warning("[LongbridgeNews] 保存新闻失败 %s: %s", stock_code, exc)

        return records

    @staticmethod
    def to_llm_context(records: Sequence[LongbridgeNewsRecord]) -> List[Dict[str, Any]]:
        return [record.to_llm_dict() for record in records]
