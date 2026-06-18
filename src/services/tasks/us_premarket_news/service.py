# -*- coding: utf-8 -*-
"""US premarket Longbridge news intelligence service."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import and_, desc, func, or_, select

from data_provider.longbridge_fetcher import LongbridgeFetcher
from data_provider.longbridge_news_fetcher import LongbridgeNewsFetcher, LongbridgeNewsRecord
from src.const.stock_index import NASDAQ100_STOCK_INDEX
from src.models import NewsIntel
from src.storage import DatabaseManager, ensure_aware_datetime

from .llm import PremarketNewsLLMAnalyzer
from .models import NewsCandidate, PremarketNewsSummary
from .notifications import PremarketNewsReporter

logger = logging.getLogger(__name__)

PREMARKET_NEWS_DIMENSION = "premarket_news"
PREMARKET_NEWS_TIMEZONE = "Asia/Shanghai"
NASDAQ100_SYMBOL_LIMIT = 20
NEWS_FETCH_LIMIT_PER_SYMBOL = 10
MAX_LLM_CANDIDATES = 80


def normalize_us_symbol(raw_symbol: str) -> str:
    """Normalize US tickers for dedup and display."""
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return ""
    if symbol.startswith("$"):
        symbol = symbol[1:]
    if symbol.endswith(".US"):
        symbol = symbol[:-3]
    return symbol


def normalize_symbols(symbols: Sequence[str]) -> List[str]:
    normalized = [normalize_us_symbol(symbol) for symbol in symbols]
    return [symbol for symbol in dict.fromkeys(normalized) if symbol]


def build_premarket_symbol_universe(watch_symbols: Sequence[str]) -> List[str]:
    """Return watch-list US symbols plus the top Nasdaq-100 symbols by market cap."""
    nasdaq_top = list(NASDAQ100_STOCK_INDEX.keys())[:NASDAQ100_SYMBOL_LIMIT]
    return normalize_symbols([*watch_symbols, *nasdaq_top])


def premarket_news_window(now: datetime) -> tuple[datetime, datetime]:
    """Return UTC bounds for yesterday 00:00 Beijing through task execution time."""
    tz = ZoneInfo(PREMARKET_NEWS_TIMEZONE)
    local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    local_start = (local_now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc), local_now.astimezone(timezone.utc)


class USPremarketNewsService:
    """Collects Longbridge news, persists it, and generates premarket intelligence."""

    def __init__(
        self,
        *,
        config: Any,
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        news_fetcher: Optional[LongbridgeNewsFetcher] = None,
        llm_analyzer: Optional[PremarketNewsLLMAnalyzer] = None,
        reporter: Optional[PremarketNewsReporter] = None,
        db: Optional[DatabaseManager] = None,
    ) -> None:
        self.config = config
        self.longbridge_fetcher = longbridge_fetcher or LongbridgeFetcher()
        self.news_fetcher = news_fetcher or LongbridgeNewsFetcher(self.longbridge_fetcher)
        self.llm_analyzer = llm_analyzer or PremarketNewsLLMAnalyzer(config)
        self.reporter = reporter or PremarketNewsReporter()
        self.db = db or DatabaseManager.get_instance()

    def run(self, watch_symbols: Sequence[str], now: Optional[datetime] = None) -> PremarketNewsSummary:
        started_at = self._scheduler_now(now)
        query_id = f"us_premarket_news_{started_at.strftime('%Y%m%d_%H%M%S')}"
        symbols = build_premarket_symbol_universe(watch_symbols)
        summary = PremarketNewsSummary(started_at=started_at, finished_at=started_at, symbols=symbols)
        logger.info("美股盘前新闻情报任务开始: symbols=%s", len(symbols))

        before_count = self._count_premarket_news_rows()
        url_symbols: Dict[str, List[str]] = {}
        for symbol in symbols:
            try:
                records = self._fetch_symbol_news(symbol, query_id=query_id)
            except Exception as exc:
                message = f"{symbol}: {exc}"
                logger.warning("美股盘前新闻抓取失败 %s", message, exc_info=True)
                summary.warnings.append(message)
                continue

            summary.fetched_news_count += len(records)
            for record in records:
                key = record.url or record.news_id
                if not key:
                    continue
                url_symbols.setdefault(key, [])
                if symbol not in url_symbols[key]:
                    url_symbols[key].append(symbol)

        after_count = self._count_premarket_news_rows()
        summary.inserted_news_count = max(after_count - before_count, 0)

        candidates = self._load_candidate_news(started_at, url_symbols)
        summary.candidates_count = len(candidates)
        candidates_by_key = {candidate.news_id_or_url: candidate for candidate in candidates}
        selected_news = self.llm_analyzer.select_important_news(candidates[:MAX_LLM_CANDIDATES])
        summary.important_news = self._backfill_selected_news(selected_news, candidates_by_key)
        summary.impact_results = self.llm_analyzer.judge_impact(summary.important_news, candidates_by_key)

        summary.finished_at = self._scheduler_now()
        summary.calendar_id = self.reporter.record_to_calendar(summary)
        summary.notification_sent = self.reporter.send_notification(summary)
        logger.info(
            "美股盘前新闻情报任务完成: symbols=%s fetched=%s inserted=%s candidates=%s top=%s warnings=%s",
            summary.symbols_count,
            summary.fetched_news_count,
            summary.inserted_news_count,
            summary.candidates_count,
            len(summary.important_news),
            len(summary.warnings),
        )
        return summary

    def _scheduler_now(self, now: Optional[datetime] = None) -> datetime:
        tz = ZoneInfo(PREMARKET_NEWS_TIMEZONE)
        return (now or datetime.now(tz)).astimezone(tz)

    def _fetch_symbol_news(self, symbol: str, *, query_id: str) -> List[LongbridgeNewsRecord]:
        stock_name = self._get_stock_name(symbol)
        return self.news_fetcher.fetch_and_save_news(
            symbol,
            name=stock_name,
            dimension=PREMARKET_NEWS_DIMENSION,
            query_id=query_id,
            limit=NEWS_FETCH_LIMIT_PER_SYMBOL,
        )

    def _get_stock_name(self, symbol: str) -> str:
        if symbol in NASDAQ100_STOCK_INDEX:
            return NASDAQ100_STOCK_INDEX[symbol]
        try:
            return self.longbridge_fetcher.get_stock_name(symbol) or ""
        except Exception:
            return ""

    def _count_premarket_news_rows(self) -> int:
        with self.db.get_session() as session:
            value = session.execute(
                select(func.count()).select_from(NewsIntel).where(NewsIntel.dimension == PREMARKET_NEWS_DIMENSION)
            ).scalar_one()
            return int(value or 0)

    def _load_candidate_news(
        self,
        run_time: datetime,
        url_symbols: Dict[str, List[str]],
    ) -> List[NewsCandidate]:
        start_utc, end_utc = premarket_news_window(run_time)
        with self.db.get_session() as session:
            stmt = (
                select(NewsIntel)
                .where(
                    NewsIntel.dimension == PREMARKET_NEWS_DIMENSION,
                    or_(
                        and_(
                            NewsIntel.published_date >= start_utc,
                            NewsIntel.published_date <= end_utc,
                        ),
                        and_(
                            NewsIntel.published_date.is_(None),
                            NewsIntel.fetched_at >= start_utc,
                            NewsIntel.fetched_at <= end_utc,
                        ),
                    ),
                )
                .order_by(desc(NewsIntel.published_date), desc(NewsIntel.fetched_at))
                .limit(MAX_LLM_CANDIDATES)
            )
            rows = session.execute(stmt).scalars().all()

        candidates: List[NewsCandidate] = []
        seen: set[str] = set()
        for row in rows:
            url = str(getattr(row, "url", "") or "").strip()
            key = url or f"{getattr(row, 'source', '')}:{getattr(row, 'title', '')}"
            if not key or key in seen:
                continue
            seen.add(key)
            row_symbol = normalize_us_symbol(getattr(row, "code", "") or "")
            related_symbols = list(dict.fromkeys([*url_symbols.get(key, []), row_symbol]))
            candidates.append(
                NewsCandidate(
                    news_id_or_url=key,
                    title=str(getattr(row, "title", "") or "").strip(),
                    description=str(getattr(row, "snippet", "") or "").strip(),
                    url=url,
                    related_symbols=[symbol for symbol in related_symbols if symbol],
                    published_at=ensure_aware_datetime(getattr(row, "published_date", None)),
                    fetched_at=ensure_aware_datetime(getattr(row, "fetched_at", None)),
                )
            )
        return candidates

    def _backfill_selected_news(
        self,
        selected_news: Sequence[Dict[str, Any]],
        candidates_by_key: Dict[str, NewsCandidate],
    ) -> List[Dict[str, Any]]:
        backfilled: List[Dict[str, Any]] = []
        for item in selected_news:
            key = str(item.get("news_id_or_url") or "").strip()
            candidate = candidates_by_key.get(key)
            if not candidate:
                backfilled.append(dict(item))
                continue
            merged = dict(item)
            merged["title"] = merged.get("title") or candidate.title
            merged["related_symbols"] = merged.get("related_symbols") or candidate.related_symbols
            backfilled.append(merged)
        return backfilled
