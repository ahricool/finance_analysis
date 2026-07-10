"""Orchestration for the A-share 14:30 holdings and market review."""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any, Callable, Optional, Sequence

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.codes import normalize_stock_code
from finance_analysis.integrations.market_data.realtime_types import safe_float
from finance_analysis.market_review.trading_calendar import (
    get_a_share_market_now,
    is_a_share_trading_day,
)
from finance_analysis.tasks.lifecycle import TaskSkipped

from .config import DEFAULT_CONFIG, MAIN_INDEX_CODES, TASK_TYPE, PreCloseReviewConfig
from .data_source import ASharePreCloseDataSource
from .llm import ASharePreCloseWebLLM
from .lock import release_lock, try_acquire_lock
from .metrics import (
    determine_market_state,
    determine_turnover_state,
    index_change_map,
    parse_snapshot_time,
    review_strong_sectors,
    screen_candidates,
)
from .models import DataQuality, PreCloseReviewSummary, SecurityReview
from .reporter import ASharePreCloseReporter
from .security_analyzer import PreCloseSecurityAnalyzer

logger = logging.getLogger(__name__)

_PRE_CLOSE_WINDOW_START = time(14, 25)
_PRE_CLOSE_WINDOW_END = time(15, 0)


class ASharePreCloseReviewService:
    def __init__(
        self,
        *,
        config: Optional[Any] = None,
        limits: PreCloseReviewConfig = DEFAULT_CONFIG,
        data_source: Optional[ASharePreCloseDataSource] = None,
        web_llm: Optional[ASharePreCloseWebLLM] = None,
        reporter: Optional[ASharePreCloseReporter] = None,
        holdings_provider: Optional[Callable[[], Sequence[Any]]] = None,
        recent_results_provider: Optional[Callable[[], Sequence[dict[str, Any]]]] = None,
        existing_news_provider: Optional[Callable[[Sequence[dict[str, Any]]], Sequence[dict[str, Any]]]] = None,
        use_lock: bool = True,
    ) -> None:
        self.config = config or self._load_pipeline_config()
        self.limits = limits
        self.data_source = data_source or ASharePreCloseDataSource()
        self.web_llm = web_llm or ASharePreCloseWebLLM(self.config, limits)
        self.reporter = reporter or ASharePreCloseReporter()
        self.holdings_provider = holdings_provider
        self.recent_results_provider = recent_results_provider
        self.existing_news_provider = existing_news_provider
        self.use_lock = use_lock

    def run(
        self,
        *,
        now: Optional[datetime] = None,
        send_notification: bool = True,
    ) -> PreCloseReviewSummary:
        task_deadline = monotonic() + self.limits.task_time_limit_seconds
        llm_deadline = task_deadline - self.limits.task_completion_reserve_seconds
        run_time = get_a_share_market_now(now)
        self._validate_trading_time(run_time)
        token = try_acquire_lock() if self.use_lock else object()
        if token is None:
            raise TaskSkipped("已有 A 股收盘前复核任务正在执行")

        try:
            previous_results = self._load_recent_results()
            if any(item.get("trading_date") == run_time.date().isoformat() for item in previous_results):
                raise TaskSkipped("当天 A 股收盘前复核已经完成")

            warnings: list[str] = []
            quality = DataQuality()
            rows = self.data_source.get_market_snapshot_rows()
            self._assess_snapshot(rows, run_time, quality)

            from ..a_share_intraday_analysis.domain_service import compute_market_breadth

            breadth = compute_market_breadth(rows, run_time.date()) if rows else {}
            indices = self._normalize_indices(self.data_source.get_main_indices())
            quality.index_coverage = len(indices)
            quality.indices_complete = len(indices) >= self.limits.minimum_index_count
            if len(indices) < self.limits.minimum_index_count:
                quality.issues.append("主要指数覆盖不足")

            ranked_top, ranked_bottom = self.data_source.get_sector_rankings(self.limits.sector_ranking_scan_limit)
            top_sectors = ranked_top[: self.limits.max_strong_sectors]
            sector_rankings = [*ranked_top, *ranked_bottom]
            quality.sector_coverage = len({str(item.get("name")) for item in sector_rankings})
            quality.sectors_complete = quality.sector_coverage >= self.limits.minimum_sector_count
            if not quality.sectors_complete:
                quality.issues.append("强势板块排行覆盖不足")

            market_state, risk_state, rationale = determine_market_state(breadth, indices)
            turnover_state = determine_turnover_state(
                safe_float(breadth.get("total_amount"), 0.0) or 0.0,
                previous_results,
            )
            strong_sectors = review_strong_sectors(
                top_sectors,
                previous_results,
                market_state=market_state,
                limit=self.limits.max_strong_sectors,
            )
            holdings = self._load_holdings()
            quality.holding_total = len(holdings)
            quote_by_code = {normalize_stock_code(str(row.get("code") or "")): row for row in rows}
            sector_changes: dict[str, float] = {}
            for item in sector_rankings:
                sector_name = str(item.get("name") or "").strip()
                sector_change = safe_float(item.get("change_pct"))
                if sector_name and sector_change is not None:
                    sector_changes[sector_name] = sector_change
            strong_sector_changes = {item.name: item.change_pct for item in strong_sectors}
            benchmark_change = self._benchmark_change(indices)
            security_analyzer = PreCloseSecurityAnalyzer(
                data_source=self.data_source,
                limits=self.limits,
                quality=quality,
                now=run_time,
                benchmark_change=benchmark_change,
            )
            market_trends = security_analyzer.load_market_trends()
            holding_reviews = security_analyzer.review_holdings(
                holdings,
                quote_by_code,
                sector_changes,
            )

            raw_candidates = screen_candidates(
                rows,
                holding_codes=[item.code for item in holding_reviews],
                limit=self.limits.max_candidates,
            )
            candidate_reviews = security_analyzer.review_candidates(
                raw_candidates,
                strong_sector_changes,
            )

            entities = self._news_entities(strong_sectors, holding_reviews, candidate_reviews, quality)
            existing_news = self._load_existing_news(entities, warnings)
            news = self.web_llm.research_news(
                entities,
                existing_news,
                trading_date=run_time.date().isoformat(),
                warnings=warnings,
                deadline=llm_deadline,
            )
            quality.news_coverage = sum(1 for item in news if item.get("coverage") != "none")
            required_news_keys = {"market:cn", *[f"stock:{item.code}" for item in holding_reviews]}
            covered_news_keys = {str(item.get("entity_key")) for item in news if item.get("coverage") != "none"}
            quality.news_complete = bool(required_news_keys) and required_news_keys.issubset(covered_news_keys)
            if entities and quality.news_coverage < len(entities):
                quality.issues.append(f"新闻覆盖 {quality.news_coverage}/{len(entities)}")
            if not quality.news_complete:
                quality.issues.append("大盘或持仓新闻覆盖不足，主动调整建议已禁用")

            context = self._build_llm_context(
                run_time,
                market_state,
                risk_state,
                turnover_state,
                rationale,
                breadth,
                indices,
                market_trends,
                strong_sectors,
                holding_reviews,
                candidate_reviews,
                news,
                quality,
            )
            decision, fallback_used = self.web_llm.decide(
                context,
                holding_reviews,
                candidate_reviews,
                quality,
                warnings=warnings,
                deadline=llm_deadline,
            )

            summary = PreCloseReviewSummary(
                trading_date=run_time.date(),
                started_at=run_time,
                finished_at=get_a_share_market_now(),
                market_state=market_state,
                market_rationale=rationale,
                turnover_state=turnover_state,
                risk_state=risk_state,
                breadth=breadth,
                indices=indices,
                market_trends=market_trends,
                strong_sectors=strong_sectors,
                holdings=holding_reviews,
                candidates=candidate_reviews,
                news=news,
                decision=decision,
                data_quality=quality,
                warnings=warnings,
                fallback_used=fallback_used,
                llm_calls=self.web_llm.call_count,
            )
            summary.calendar_id = self.reporter.record_to_calendar(summary)
            summary.notification_sent = self.reporter.send_notification(
                summary,
                send_notification=send_notification,
            )
            return summary
        finally:
            if self.use_lock:
                release_lock(token)

    def _validate_trading_time(self, now: datetime) -> None:
        if now.weekday() >= 5 or not is_a_share_trading_day(now.date(), now):
            raise TaskSkipped("当天不是 A 股交易日")
        if not (_PRE_CLOSE_WINDOW_START <= now.time() <= _PRE_CLOSE_WINDOW_END):
            raise TaskSkipped("当前不在 A 股收盘前复核时段")

    def _assess_snapshot(
        self,
        rows: Sequence[dict[str, Any]],
        now: datetime,
        quality: DataQuality,
    ) -> None:
        quality.market_rows = len(rows)
        quality.market_complete = len(rows) >= self.limits.minimum_market_rows
        if not quality.market_complete:
            quality.issues.append(f"全市场行情覆盖不足: {len(rows)}/{self.limits.minimum_market_rows}")
        snapshot_time = parse_snapshot_time(rows)
        quality.snapshot_time = snapshot_time
        if snapshot_time is None:
            quality.issues.append("全市场行情缺少可校验的快照时间")
            return
        local_snapshot = snapshot_time.astimezone(now.tzinfo)
        age = int((now - local_snapshot).total_seconds())
        if age < -180:
            quality.issues.append("行情快照时间明显晚于任务时间")
            return
        age = max(0, age)
        quality.quote_age_seconds = age
        quality.fresh_quotes = age <= self.limits.max_quote_age_seconds
        if not quality.fresh_quotes:
            level = "严重过期" if age > self.limits.critical_quote_age_seconds else "过期"
            quality.issues.append(f"全市场行情{level}: {age} 秒")

    def _load_holdings(self) -> list[Any]:
        if self.holdings_provider is not None:
            raw = self.holdings_provider()
        else:
            from finance_analysis.database.repositories.stock_list import StockListRepo
            from finance_analysis.database.repositories.user import UserRepository

            uid = int(UserRepository().ensure_default_admin())
            raw = StockListRepo().list_all(uid=uid)
        output = []
        for item in raw or []:
            market = str(self._field(item, "market_type") or "").upper()
            quantity = self._decimal(self._field(item, "quantity"))
            code = normalize_stock_code(str(self._field(item, "code") or ""))
            if market == "CN" and quantity > 0 and code:
                output.append(item)
        return output

    def _load_recent_results(self) -> list[dict[str, Any]]:
        if self.recent_results_provider is not None:
            return [dict(item) for item in self.recent_results_provider()]
        try:
            from finance_analysis.database.repositories.task_record import TaskRecordRepository

            records = TaskRecordRepository().list_tasks(
                task_type=TASK_TYPE,
                statuses=["completed"],
                limit=self.limits.recent_result_count,
            )
            output = []
            for record in records:
                parsed = json.loads(record.result) if isinstance(record.result, str) else record.result
                if isinstance(parsed, dict):
                    output.append(parsed)
            return output
        except Exception as exc:
            logger.warning("读取最近 A 股收盘前复核结果失败: %s", exc)
            return []

    def _news_entities(
        self,
        sectors: Sequence[Any],
        holdings: Sequence[SecurityReview],
        candidates: Sequence[SecurityReview],
        quality: DataQuality,
    ) -> list[dict[str, Any]]:
        entities = [{"key": "market:cn", "type": "market", "name": "A股市场", "code": ""}]
        entities.extend(
            {"key": f"stock:{item.code}", "type": "holding", "name": item.name, "code": item.code} for item in holdings
        )
        entities.extend(
            {"key": f"sector:{item.name}", "type": "sector", "name": item.name, "code": ""} for item in sectors
        )
        entities.extend(
            {"key": f"stock:{item.code}", "type": "candidate", "name": item.name, "code": item.code}
            for item in candidates
        )
        deduped = list({item["key"]: item for item in entities}.values())
        if len(deduped) > self.limits.max_news_entities:
            quality.issues.append(f"新闻研究实体已从 {len(deduped)} 个截断至 {self.limits.max_news_entities} 个")
        return deduped[: self.limits.max_news_entities]

    def _load_existing_news(
        self,
        entities: Sequence[dict[str, Any]],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if self.existing_news_provider is not None:
            return [dict(item) for item in self.existing_news_provider(entities)]
        code_to_key = {item["code"]: item["key"] for item in entities if item.get("code")}
        if not code_to_key:
            return []
        try:
            from sqlalchemy import desc, select

            from finance_analysis.database import DatabaseManager
            from finance_analysis.database.models import NewsIntel

            with DatabaseManager.get_instance().get_session() as session:
                rows = (
                    session.execute(
                        select(NewsIntel)
                        .where(
                            NewsIntel.code.in_(list(code_to_key)),
                            NewsIntel.fetched_at >= utc_now() - timedelta(days=7),
                        )
                        .order_by(desc(NewsIntel.published_date))
                        .limit(30)
                    )
                    .scalars()
                    .all()
                )
            return [
                {
                    "entity_key": code_to_key.get(str(item.code), ""),
                    "title": str(item.title or "")[:180],
                    "snippet": str(item.snippet or "")[:500],
                    "url": str(item.url or "")[:500],
                    "published_at": item.published_date.isoformat() if item.published_date else None,
                }
                for item in rows
            ]
        except Exception as exc:
            logger.warning("读取已有新闻存储失败: %s", exc)
            warnings.append(f"已有新闻读取失败: {str(exc)[:160]}")
            return []

    def _build_llm_context(
        self,
        run_time: datetime,
        market_state: str,
        risk_state: str,
        turnover_state: str,
        rationale: Sequence[str],
        breadth: dict[str, Any],
        indices: Sequence[dict[str, Any]],
        market_trends: Sequence[dict[str, Any]],
        sectors: Sequence[Any],
        holdings: Sequence[SecurityReview],
        candidates: Sequence[SecurityReview],
        news: Sequence[dict[str, Any]],
        quality: DataQuality,
    ) -> dict[str, Any]:
        return {
            "task_time": run_time.isoformat(),
            "market": {
                "state": market_state,
                "risk_state": risk_state,
                "turnover_state": turnover_state,
                "rationale": list(rationale),
                "breadth": breadth,
                "indices": list(indices),
                "recent_trends": list(market_trends),
            },
            "strong_sectors": [item.to_dict() for item in sectors],
            "holdings": [item.to_dict() for item in holdings],
            "candidates": [item.to_dict() for item in candidates],
            "news_research": list(news),
            "data_quality": quality.to_dict(),
            "constraints": {
                "advice_is_percentage_of_each_current_holding": True,
                "no_share_counts": True,
                "no_account_total_position_or_cash_inference": True,
                "t_plus_one_confirmation_required": True,
            },
        }

    @staticmethod
    def _normalize_indices(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        output = []
        for item in rows:
            code = normalize_stock_code(str(item.get("code") or ""))
            change = safe_float(item.get("change_pct"))
            if code not in MAIN_INDEX_CODES or change is None:
                continue
            output.append(
                {
                    "code": code,
                    "name": str(item.get("name") or MAIN_INDEX_CODES[code]),
                    "price": safe_float(item.get("current") or item.get("price")),
                    "change_pct": round(change, 3),
                    "amount": safe_float(item.get("amount")),
                }
            )
        return output

    @staticmethod
    def _benchmark_change(indices: Sequence[dict[str, Any]]) -> Optional[float]:
        changes = index_change_map(indices)
        if "000300" in changes:
            return changes["000300"]
        values = list(changes.values())
        return sum(values) / len(values) if values else None

    @staticmethod
    def _field(item: Any, name: str) -> Any:
        return item.get(name) if isinstance(item, dict) else getattr(item, name, None)

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value or 0))
        except Exception:
            return Decimal("0")

    @staticmethod
    def _load_pipeline_config() -> Any:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config

        return get_pipeline_config()


__all__ = ["ASharePreCloseReviewService"]
