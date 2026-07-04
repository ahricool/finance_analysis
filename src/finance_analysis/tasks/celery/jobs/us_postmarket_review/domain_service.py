# -*- coding: utf-8 -*-
"""Business service for the scheduled US post-market review."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import desc, or_, select

from finance_analysis.core.time import utc_now
from finance_analysis.database import DatabaseManager, ensure_aware_datetime
from finance_analysis.database.models import NewsIntel
from finance_analysis.integrations.market_data.realtime_types import safe_float, safe_int
from finance_analysis.market_review.trading_calendar import (
    get_effective_trading_date,
    get_market_now,
    is_market_open,
    is_market_session_closed,
)
from finance_analysis.reporting.localization import normalize_report_language
from finance_analysis.tasks.lifecycle import TaskSkipped

from .lock import release_us_postmarket_review_lock, try_acquire_us_postmarket_review_lock
from .models import (
    InstrumentPerformance,
    US_POSTMARKET_BENCHMARKS,
    US_POSTMARKET_SECTOR_ETFS,
    USPostmarketReviewContext,
    USPostmarketReviewSummary,
    WatchlistSummary,
)
from .reporter import USPostmarketReviewReporter

logger = logging.getLogger(__name__)

_OUTPERFORM_THRESHOLD_PCT = 1.0
_UNUSUAL_VOLUME_RATIO = 1.5
_FLAT_THRESHOLD_PCT = 0.05
_NEWS_LIMIT = 15


class USPostmarketReviewService:
    """Generate and persist a Chinese Markdown recap after the US cash close."""

    def __init__(
        self,
        *,
        config: Optional[Any] = None,
        history_loader: Optional[Callable[..., Any]] = None,
        search_service: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        reporter: Optional[USPostmarketReviewReporter] = None,
        watch_symbols_provider: Optional[Callable[[], Sequence[str]]] = None,
        db: Optional[DatabaseManager] = None,
    ) -> None:
        self.config = config or self._load_config()
        if history_loader is None:
            from finance_analysis.analysis.history.loader import load_history_df

            history_loader = load_history_df
        self.history_loader = history_loader
        self.search_service = search_service
        self.llm_client = llm_client
        self.reporter = reporter or USPostmarketReviewReporter()
        self.watch_symbols_provider = watch_symbols_provider
        self.db = db or DatabaseManager.get_instance()

        if self.search_service is None:
            self.search_service = self._build_search_service()

    def run(
        self,
        *,
        now: Optional[datetime] = None,
        send_notification: bool = True,
    ) -> USPostmarketReviewSummary:
        started_at = self._market_now(now)
        trading_date = self._validate_trading_day_and_close(started_at)
        summary = USPostmarketReviewSummary(
            trading_date=trading_date,
            started_at=started_at,
            finished_at=started_at,
        )
        lock_key = f"us_postmarket_review:{trading_date.isoformat()}"
        lock_token = try_acquire_us_postmarket_review_lock(lock_key)
        if lock_token is None:
            raise TaskSkipped("同一交易日美股收盘复盘正在执行")

        try:
            logger.info("美股收盘复盘开始: trading_date=%s", trading_date.isoformat())
            context = self._build_context(trading_date)
            summary.warnings.extend(context.warnings)
            summary.benchmark_count = len(context.benchmarks)
            summary.sector_count = len(context.sector_etfs)
            summary.watchlist_count = context.watchlist_summary.total_count
            summary.watchlist_up_count = context.watchlist_summary.up_count
            summary.watchlist_down_count = context.watchlist_summary.down_count
            summary.market_regime = context.market_regime

            if not context.benchmarks:
                raise RuntimeError("所有主要指数行情均无法获取")

            report = self._generate_llm_report(context, summary.warnings)
            if not report:
                summary.fallback_used = True
                report = self._generate_fallback_report(context)
            summary.report = self._ensure_required_sections(report, context)

            summary.finished_at = self._market_now()
            summary.report_file = self.reporter.save_report_file(summary)
            summary.calendar_id = self.reporter.record_to_calendar(summary)
            summary.notification_sent = self.reporter.send_notification(
                summary,
                send_notification=send_notification,
            )
            logger.info(
                "美股收盘复盘完成: trading_date=%s regime=%s benchmarks=%s sectors=%s watchlist=%s warnings=%s",
                trading_date.isoformat(),
                summary.market_regime,
                summary.benchmark_count,
                summary.sector_count,
                summary.watchlist_count,
                len(summary.warnings),
            )
            return summary
        finally:
            release_us_postmarket_review_lock(lock_token)

    def _validate_trading_day_and_close(self, now: datetime) -> date:
        local_date = now.date()
        if not is_market_open("us", local_date):
            logger.info("美股收盘复盘跳过: %s 不是美股交易日", local_date.isoformat())
            raise TaskSkipped("当天不是美股交易日")
        if not is_market_session_closed("us", current_time=now, check_date=local_date):
            logger.info("美股收盘复盘跳过: %s 尚未收盘 now=%s", local_date.isoformat(), now.isoformat())
            raise TaskSkipped("美股尚未收盘")

        effective_date = get_effective_trading_date("us", current_time=now)
        if effective_date != local_date:
            raise TaskSkipped("美股尚未收盘")
        return local_date

    def _build_context(self, trading_date: date) -> USPostmarketReviewContext:
        warnings: List[str] = []
        benchmarks = self._load_performance_group(
            US_POSTMARKET_BENCHMARKS,
            trading_date,
            warnings,
        )
        spy_change = self._find_change_pct(benchmarks, "SPY.US")
        qqq_change = self._find_change_pct(benchmarks, "QQQ.US")
        self._apply_relative_returns(benchmarks, spy_change=spy_change, qqq_change=qqq_change)

        sectors = self._load_performance_group(
            US_POSTMARKET_SECTOR_ETFS,
            trading_date,
            warnings,
        )
        self._apply_relative_returns(sectors, spy_change=spy_change, qqq_change=qqq_change)
        sector_top3 = sorted(sectors, key=lambda item: item.change_pct, reverse=True)[:3]
        sector_bottom3 = sorted(sectors, key=lambda item: item.change_pct)[:3]
        style_bias = self._determine_style_bias(sectors)
        market_regime = self._determine_market_regime(benchmarks, sectors, style_bias)

        watch_symbols = self._load_watch_symbols()
        watchlist_summary = self._build_watchlist_summary(
            watch_symbols,
            trading_date,
            qqq_change,
            spy_change,
            warnings,
        )
        news = self._load_news(trading_date, watch_symbols, warnings)
        return USPostmarketReviewContext(
            trading_date=trading_date,
            benchmarks=benchmarks,
            sector_etfs=sectors,
            sector_top3=sector_top3,
            sector_bottom3=sector_bottom3,
            style_bias=style_bias,
            market_regime=market_regime,
            watchlist_summary=watchlist_summary,
            news=news,
            warnings=warnings,
        )

    def _load_performance_group(
        self,
        symbols: Dict[str, str],
        trading_date: date,
        warnings: List[str],
    ) -> List[InstrumentPerformance]:
        items: List[InstrumentPerformance] = []
        for symbol, name in symbols.items():
            try:
                items.append(self._fetch_daily_performance(symbol, name, trading_date))
            except Exception as exc:
                logger.warning("美股收盘复盘行情获取失败 %s: %s", symbol, exc, exc_info=True)
                warnings.append(f"{symbol} 行情获取失败: {exc}")
        return items

    def _fetch_daily_performance(
        self,
        symbol: str,
        name: str,
        trading_date: date,
    ) -> InstrumentPerformance:
        df, source = self.history_loader(symbol, target_date=trading_date, days=35)

        rows = self._rows_until_trading_date(df, trading_date)
        if not rows:
            raise RuntimeError("未找到交易日之前的日线数据")

        latest = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else None
        close = safe_float(latest.get("close"))
        if close is None or close <= 0:
            raise RuntimeError("收盘价缺失")
        change_pct = safe_float(latest.get("pct_chg"))
        if change_pct is None and previous is not None:
            prev_close = safe_float(previous.get("close"))
            change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0.0
        volume = safe_int(latest.get("volume"), 0) or 0
        previous_volumes = [
            safe_float(row.get("volume"), 0.0) or 0.0
            for row in rows[-21:-1]
            if safe_float(row.get("volume"), 0.0) is not None
        ]
        volume_ratio = None
        if len(previous_volumes) >= 5:
            avg_volume = sum(previous_volumes) / len(previous_volumes)
            if avg_volume > 0:
                volume_ratio = volume / avg_volume

        return InstrumentPerformance(
            symbol=symbol,
            name=name,
            close=float(close),
            change_pct=float(change_pct or 0.0),
            volume=int(volume),
            volume_ratio=volume_ratio,
            source=str(source or ""),
        )

    def _rows_until_trading_date(self, df: Any, trading_date: date) -> List[Dict[str, Any]]:
        records = df.to_dict("records")
        rows: List[Dict[str, Any]] = []
        for record in records:
            row_date = self._coerce_row_date(record.get("date"))
            if row_date is None or row_date <= trading_date:
                rows.append(record)
        return rows

    @staticmethod
    def _coerce_row_date(value: Any) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            parsed = datetime.fromisoformat(str(value)[:10])
            return parsed.date()
        except ValueError:
            return None

    @staticmethod
    def _find_change_pct(items: Sequence[InstrumentPerformance], symbol: str) -> Optional[float]:
        for item in items:
            if item.symbol == symbol:
                return item.change_pct
        return None

    @staticmethod
    def _apply_relative_returns(
        items: Iterable[InstrumentPerformance],
        *,
        spy_change: Optional[float],
        qqq_change: Optional[float],
    ) -> None:
        for item in items:
            if spy_change is not None:
                item.relative_to_spy = item.change_pct - spy_change
            if qqq_change is not None:
                item.relative_to_qqq = item.change_pct - qqq_change

    def _load_watch_symbols(self) -> List[str]:
        if self.watch_symbols_provider is not None:
            raw_symbols = self.watch_symbols_provider()
        else:
            from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market

            raw_symbols = get_watch_list_codes_by_market("US")
        symbols = [self._normalize_us_symbol(symbol) for symbol in raw_symbols]
        return [symbol for symbol in dict.fromkeys(symbols) if symbol]

    def _build_watchlist_summary(
        self,
        symbols: Sequence[str],
        trading_date: date,
        qqq_change: Optional[float],
        spy_change: Optional[float],
        warnings: List[str],
    ) -> WatchlistSummary:
        summary = WatchlistSummary()
        if not symbols:
            warnings.append("未配置美股自选股")
            return summary

        performances: List[InstrumentPerformance] = []
        for symbol in symbols:
            try:
                item = self._fetch_daily_performance(symbol, symbol, trading_date)
                self._apply_relative_returns([item], spy_change=spy_change, qqq_change=qqq_change)
                performances.append(item)
            except Exception as exc:
                logger.warning("美股自选股行情获取失败 %s: %s", symbol, exc, exc_info=True)
                warnings.append(f"{symbol} 自选股行情获取失败: {exc}")

        summary.total_count = len(performances)
        if not performances:
            return summary

        summary.up_count = sum(1 for item in performances if item.change_pct > _FLAT_THRESHOLD_PCT)
        summary.down_count = sum(1 for item in performances if item.change_pct < -_FLAT_THRESHOLD_PCT)
        summary.flat_count = len(performances) - summary.up_count - summary.down_count
        summary.average_change_pct = sum(item.change_pct for item in performances) / len(performances)
        summary.gainers = sorted(performances, key=lambda item: item.change_pct, reverse=True)[:5]
        summary.losers = sorted(performances, key=lambda item: item.change_pct)[:5]
        if qqq_change is not None:
            summary.outperform_qqq = [
                item for item in performances if (item.relative_to_qqq or 0.0) >= _OUTPERFORM_THRESHOLD_PCT
            ][:8]
            summary.underperform_qqq = [
                item for item in performances if (item.relative_to_qqq or 0.0) <= -_OUTPERFORM_THRESHOLD_PCT
            ][:8]
        summary.unusual_volume = [
            item for item in performances if (item.volume_ratio or 0.0) >= _UNUSUAL_VOLUME_RATIO
        ][:8]
        return summary

    def _load_news(
        self,
        trading_date: date,
        watch_symbols: Sequence[str],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        news = self._load_persisted_news(watch_symbols, warnings)
        if len(news) < 10:
            news.extend(self._search_news(watch_symbols, warnings))
        return self._dedupe_news(news)[:_NEWS_LIMIT]

    def _load_persisted_news(
        self,
        watch_symbols: Sequence[str],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        try:
            end_utc = utc_now()
            start_utc = end_utc - timedelta(hours=24)
            codes = {"market", "SPY.US", "QQQ.US", *watch_symbols}
            with self.db.get_session() as session:
                stmt = (
                    select(NewsIntel)
                    .where(
                        NewsIntel.code.in_(codes),
                        or_(
                            NewsIntel.published_date >= start_utc,
                            NewsIntel.fetched_at >= start_utc,
                        ),
                    )
                    .order_by(desc(NewsIntel.published_date), desc(NewsIntel.fetched_at))
                    .limit(_NEWS_LIMIT)
                )
                rows = session.execute(stmt).scalars().all()
            return [
                {
                    "title": str(row.title or "")[:180],
                    "summary": str(row.snippet or "")[:500],
                    "source": str(row.source or row.provider or "")[:80],
                    "published_at": self._format_dt(ensure_aware_datetime(row.published_date)),
                    "url": str(row.url or "")[:500],
                    "related_symbols": [self._normalize_us_symbol(row.code)] if row.code else [],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("读取已保存美股新闻失败: %s", exc, exc_info=True)
            warnings.append(f"读取已保存新闻失败: {exc}")
            return []

    def _search_news(self, watch_symbols: Sequence[str], warnings: List[str]) -> List[Dict[str, Any]]:
        if self.search_service is None:
            warnings.append("搜索服务未配置，跳过新闻搜索")
            return []
        queries = [
            "S&P 500 Nasdaq Dow close today performance",
            "US stocks close market drivers today",
            "Federal Reserve rates inflation US stocks today",
            "US technology stocks sectors market close today",
        ]
        if watch_symbols:
            queries.append(" ".join([*watch_symbols[:8], "stock news today earnings guidance"]))

        results: List[Dict[str, Any]] = []
        for query in queries:
            try:
                response = self.search_service.search_stock_news(
                    stock_code="market",
                    stock_name="US market",
                    max_results=3,
                    focus_keywords=query.split(),
                )
                for item in getattr(response, "results", []) or []:
                    results.append(
                        {
                            "title": self._field(item, "title")[:180],
                            "summary": self._field(item, "snippet")[:500],
                            "source": self._field(item, "source")[:80],
                            "published_at": self._field(item, "published_date")[:80],
                            "url": self._field(item, "url")[:500],
                            "related_symbols": [],
                        }
                    )
            except Exception as exc:
                logger.warning("美股收盘复盘新闻搜索失败 query=%s: %s", query, exc, exc_info=True)
                warnings.append(f"新闻搜索失败: {exc}")
        return results

    @staticmethod
    def _dedupe_news(news: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in news:
            key = str(item.get("url") or item.get("title") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(dict(item))
        return deduped

    def _generate_llm_report(
        self,
        context: USPostmarketReviewContext,
        warnings: List[str],
    ) -> Optional[str]:
        try:
            client = self._get_llm_client()
            if client is None or not client.is_available():
                warnings.append("LLM 未配置，使用确定性降级报告")
                return None
            payload = context.to_llm_payload()
            from finance_analysis.llm import LLMRequest

            result = client.complete_text(
                LLMRequest(
                    messages=[
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": self._user_prompt(payload)},
                    ],
                    temperature=0.2,
                    max_tokens=9000,
                    timeout=120,
                    call_type="us_postmarket_review",
                )
            )
            text = str(getattr(result, "text", "") or "").strip()
            if not text:
                warnings.append("LLM 返回空内容，使用确定性降级报告")
                return None
            return text
        except Exception as exc:
            logger.warning("美股收盘复盘 LLM 生成失败: %s", exc, exc_info=True)
            warnings.append(f"LLM 生成失败: {exc}")
            return None

    def _get_llm_client(self) -> Optional[Any]:
        if self.llm_client is not None:
            return self.llm_client
        try:
            from finance_analysis.llm import LLMClient

            self.llm_client = LLMClient(config=self.config)
            return self.llm_client
        except Exception as exc:
            logger.warning("初始化 LLMClient 失败: %s", exc, exc_info=True)
            return None

    def _system_prompt(self) -> str:
        language = normalize_report_language(getattr(self.config, "report_language", "zh"))
        language_rule = "报告语言使用中文。" if language == "zh" else "报告语言优先使用配置语言，但章节标题保持指定结构。"
        return (
            "你是谨慎的美股收盘复盘分析师。"
            "只能根据用户输入的结构化数据分析，不得编造价格、涨跌幅、新闻或宏观事件；"
            "数据缺失时必须明确说明。区分事实、推断和策略建议；"
            "不输出绝对化买入卖出指令，不使用“必涨”“必跌”等表达；"
            "报告以复盘和风险识别为主，结论必须能在输入数据中找到依据。"
            f"{language_rule}"
        )

    @staticmethod
    def _user_prompt(payload: Dict[str, Any]) -> str:
        return (
            "请基于以下 JSON 数据生成中文 Markdown 美股收盘复盘报告。\n\n"
            "必须严格包含以下章节：\n"
            "# 美股收盘复盘 - YYYY-MM-DD\n"
            "## 1. 今日市场结论\n"
            "## 2. 主要指数表现\n"
            "## 3. 板块强弱与资金风格\n"
            "## 4. 自选股表现\n"
            "## 5. 今日市场主要驱动\n"
            "## 6. 风险信号\n"
            "## 7. 下一交易日关注事项\n"
            "## 8. 数据说明\n\n"
            "今日市场结论必须给出 risk_on / neutral / risk_off 之一并解释依据。"
            "下一交易日关注事项必须包含关键指数或 ETF 观察位、强弱板块延续性、"
            "自选股重点、已知财报或宏观事件，以及判断失效条件。"
            "不得补充输入中不存在的新闻或宏观事件。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _generate_fallback_report(self, context: USPostmarketReviewContext) -> str:
        watch = context.watchlist_summary
        lines = [
            f"# 美股收盘复盘 - {context.trading_date.isoformat()}",
            "",
            "## 1. 今日市场结论",
            "",
            f"- **市场状态**：{context.market_regime}",
            f"- **规则判断**：主要指数与板块风格显示当前偏 {context.style_bias}。",
            "- **说明**：AI 分析暂不可用，以下为基于行情数据的确定性降级报告。",
            "",
            "## 2. 主要指数表现",
            "",
            self._performance_table(context.benchmarks, include_spy=False),
            "",
            "## 3. 板块强弱与资金风格",
            "",
            f"- **风格判断**：{context.style_bias}",
            "- **涨幅前三**：" + self._join_symbols(context.sector_top3),
            "- **跌幅前三**：" + self._join_symbols(context.sector_bottom3),
            "",
            self._performance_table(context.sector_etfs),
            "",
            "## 4. 自选股表现",
            "",
            f"- 自选股总数：{watch.total_count}",
            f"- 上涨/下跌/平盘：{watch.up_count} / {watch.down_count} / {watch.flat_count}",
            f"- 平均涨跌幅：{watch.average_change_pct:+.2f}%",
            "- 涨幅前五：" + self._join_symbols(watch.gainers),
            "- 跌幅前五：" + self._join_symbols(watch.losers),
            "- 明显跑赢 QQQ：" + self._join_symbols(watch.outperform_qqq),
            "- 明显跑输 QQQ：" + self._join_symbols(watch.underperform_qqq),
            "- 成交量显著放大：" + self._join_symbols(watch.unusual_volume),
            "",
            "## 5. 今日市场主要驱动",
            "",
        ]
        if context.news:
            lines.extend(
                f"- {item.get('title', '-')}: {item.get('summary', '')}"[:500]
                for item in context.news[:8]
            )
        else:
            lines.append("- 暂无可用新闻输入，不能推断具体新闻驱动。")
        lines.extend(
            [
                "",
                "## 6. 风险信号",
                "",
                "- 若主要指数与领涨板块背离扩大，需警惕风险偏好回落。",
                "- 若弱势板块继续跑输 SPY，说明资金分化尚未缓解。",
                "",
                "## 7. 下一交易日关注事项",
                "",
                "- 关键指数或 ETF：观察 SPY、QQQ、IWM 能否延续当日方向。",
                f"- 强势板块能否延续：{self._join_symbols(context.sector_top3)}。",
                f"- 弱势板块风险：{self._join_symbols(context.sector_bottom3)}。",
                f"- 自选股重点：{self._join_symbols(watch.gainers[:3] + watch.unusual_volume[:3])}。",
                "- 已知财报或宏观事件：仅依据输入新闻，未提供则不作推断。",
                "- 判断失效条件：SPY/QQQ 与当前风险偏好方向相反且板块扩散失败。",
                "",
                "## 8. 数据说明",
                "",
                "- AI 分析暂不可用，报告由确定性模板生成。",
            ]
        )
        if context.warnings:
            lines.extend(["- 数据获取 warnings：", *[f"  - {item}" for item in context.warnings[:20]]])
        return "\n".join(lines).strip()

    def _ensure_required_sections(self, report: str, context: USPostmarketReviewContext) -> str:
        required = [
            "# 美股收盘复盘 -",
            "## 1. 今日市场结论",
            "## 2. 主要指数表现",
            "## 3. 板块强弱与资金风格",
            "## 4. 自选股表现",
            "## 5. 今日市场主要驱动",
            "## 6. 风险信号",
            "## 7. 下一交易日关注事项",
            "## 8. 数据说明",
        ]
        if all(section in report for section in required):
            return report.strip()
        logger.warning("LLM 报告缺少规定章节，切换为降级报告")
        return self._generate_fallback_report(context)

    @staticmethod
    def _performance_table(
        items: Sequence[InstrumentPerformance],
        *,
        include_spy: bool = True,
    ) -> str:
        if not items:
            return "暂无数据。"
        header = "| 标的 | 名称 | 收盘价 | 涨跌幅 | 成交量 | 量比 | 相对SPY |"
        sep = "|------|------|--------|--------|--------|------|---------|"
        rows = [header, sep]
        for item in items:
            relative = "-" if item.relative_to_spy is None or not include_spy else f"{item.relative_to_spy:+.2f}%"
            volume_ratio = "-" if item.volume_ratio is None else f"{item.volume_ratio:.2f}"
            rows.append(
                f"| {item.symbol} | {item.name} | {item.close:.2f} | {item.change_pct:+.2f}% | "
                f"{item.volume} | {volume_ratio} | {relative} |"
            )
        return "\n".join(rows)

    @staticmethod
    def _join_symbols(items: Sequence[InstrumentPerformance]) -> str:
        if not items:
            return "暂无"
        return "、".join(f"{item.symbol}({item.change_pct:+.2f}%)" for item in items)

    @staticmethod
    def _determine_style_bias(items: Sequence[InstrumentPerformance]) -> str:
        scores = {
            "成长": ["XLK.US", "SOXX.US", "XLY.US"],
            "价值": ["XLF.US", "XLE.US"],
            "周期": ["XLE.US", "XLI.US", "XLB.US", "XLRE.US"],
            "防御": ["XLP.US", "XLV.US", "XLU.US"],
        }
        change_by_symbol = {item.symbol: item.change_pct for item in items}
        averages: Dict[str, float] = {}
        for style, symbols in scores.items():
            values = [change_by_symbol[symbol] for symbol in symbols if symbol in change_by_symbol]
            if values:
                averages[style] = sum(values) / len(values)
        if not averages:
            return "中性"
        ordered = sorted(averages.items(), key=lambda item: item[1], reverse=True)
        if len(ordered) > 1 and ordered[0][1] - ordered[1][1] < 0.2:
            return "中性"
        return ordered[0][0]

    def _determine_market_regime(
        self,
        benchmarks: Sequence[InstrumentPerformance],
        sectors: Sequence[InstrumentPerformance],
        style_bias: str,
    ) -> str:
        changes = {item.symbol: item.change_pct for item in benchmarks}
        spy = changes.get("SPY.US", 0.0)
        qqq = changes.get("QQQ.US", 0.0)
        iwm = changes.get("IWM.US", 0.0)
        defensive_lead = style_bias == "防御" and spy <= 0.2
        sector_avg = sum(item.change_pct for item in sectors) / len(sectors) if sectors else 0.0
        if spy >= 0.5 and qqq >= 0.3 and iwm >= -0.2 and sector_avg >= 0:
            return "risk_on"
        if spy <= -0.5 and qqq <= 0.0:
            return "risk_off"
        if defensive_lead and qqq < 0:
            return "risk_off"
        return "neutral"

    def _market_now(self, now: Optional[datetime] = None) -> datetime:
        return get_market_now("us", current_time=now)

    @staticmethod
    def _normalize_us_symbol(raw_symbol: str) -> str:
        symbol = str(raw_symbol or "").strip().upper()
        if symbol.startswith("$"):
            symbol = symbol[1:]
        return symbol if symbol.endswith(".US") else ""

    @staticmethod
    def _field(item: Any, field: str) -> str:
        if hasattr(item, field):
            return str(getattr(item, field) or "").strip()
        if isinstance(item, dict):
            return str(item.get(field) or "").strip()
        return ""

    @staticmethod
    def _format_dt(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    @staticmethod
    def _load_config() -> Any:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config

        return get_pipeline_config()

    def _build_search_service(self) -> Optional[Any]:
        try:
            has_search_capability = getattr(self.config, "has_search_capability_enabled", None)
            if callable(has_search_capability) and not has_search_capability():
                return None
            from finance_analysis.market_review.runtime import build_market_review_runtime

            _, _, search_service = build_market_review_runtime(self.config)
            return search_service
        except Exception as exc:
            logger.warning("初始化美股收盘复盘搜索服务失败: %s", exc, exc_info=True)
            return None
