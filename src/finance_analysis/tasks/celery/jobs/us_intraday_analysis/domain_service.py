# -*- coding: utf-8 -*-
"""US intraday anomaly detection service.

This task is alert-oriented: on every run it pulls the latest intraday data on
demand, computes rule-based candidates, and asks the LLM to decide whether the
signal is worth surfacing. The orchestration here wires together the focused
modules: data fetching, metric computation, rule evaluation, LLM judging and
notification delivery.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.providers.longbridge.news import LongbridgeNewsFetcher
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher
from finance_analysis.tasks.celery.jobs.intraday_signal_state import (
    IntradaySignalStateStore,
    build_notification_signature,
)
from finance_analysis.tasks.lifecycle import TaskSkipped

from .config import INTRADAY_NEWS_LIMIT, LLM_BATCH_SIZE, MARKET_ETFS, MARKET_NEWS_SYMBOL, STALE_BAR_SECONDS, US_EASTERN
from .data_source import IntradayDataSource
from .llm import IntradayLLMJudge, candidate_id, truthy
from .lock import release_us_intraday_running_lock, try_acquire_us_intraday_lock
from .market_calendar import get_us_trading_date, is_us_market_open, parse_timestamp
from .metrics import compute_intraday_metrics
from .models import IntradaySignalResult, IntradayTaskSummary
from .notifications import SignalReporter
from .rules import DEFAULT_INTRADAY_SIGNAL_RULES, RulePredicate, evaluate_signal_candidates_with_diagnostics

logger = logging.getLogger(__name__)

_MIN_BARS_FOR_SYMBOL = 15
_MIN_BARS_FOR_BENCHMARK = 10
_NOTIFY_DECISIONS = {"watch", "risk"}


class USIntradayAnalysisService:
    """Detects intraday anomalies on watched US symbols and alerts on them."""

    def __init__(
        self,
        *,
        config: Any,
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        yfinance_fetcher: Optional[YfinanceFetcher] = None,
        news_fetcher: Optional[LongbridgeNewsFetcher] = None,
        rules: Optional[Sequence[RulePredicate]] = None,
        use_lock: bool = True,
        lock_client: Any = None,
        signal_state_store: Optional[IntradaySignalStateStore] = None,
    ) -> None:
        self.config = config
        self.longbridge_fetcher = longbridge_fetcher or LongbridgeFetcher()
        self.data_source = IntradayDataSource(self.longbridge_fetcher, yfinance_fetcher)
        self.news_fetcher = news_fetcher or LongbridgeNewsFetcher(self.longbridge_fetcher)
        self.llm_judge = IntradayLLMJudge(config)
        self.reporter = SignalReporter()
        self.rules: Sequence[RulePredicate] = rules if rules is not None else DEFAULT_INTRADAY_SIGNAL_RULES
        self.use_lock = use_lock
        self.lock_client = lock_client
        self.signal_state_store = signal_state_store or IntradaySignalStateStore()
        self._news_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._run_query_id = ""
        self._run_time: Optional[datetime] = None
        self._state_observed_symbols: set[str] = set()

    def run(self, stock_codes: Sequence[str], now: Optional[datetime] = None) -> IntradayTaskSummary:
        if not is_us_market_open(now):
            return IntradayTaskSummary(market_open=False, total_symbols=len(stock_codes))

        started = time.perf_counter()
        run_time = _eastern_now(now)
        self._run_time = run_time
        self._run_query_id = f"us_intraday_{run_time.strftime('%Y%m%d_%H%M%S')}"
        self._news_cache = {}
        self._state_observed_symbols = set()

        summary = IntradayTaskSummary(market_open=True, total_symbols=len(stock_codes))
        summary.timings["started_at"] = run_time.isoformat()
        lock_token = None
        try:
            if self.use_lock:
                lock_token = try_acquire_us_intraday_lock(
                    trading_date=get_us_trading_date(run_time),
                    window_time=run_time.strftime("%H:%M"),
                    client=self.lock_client,
                )
                if lock_token is None:
                    raise TaskSkipped("美股盘中分析任务正在执行或当前窗口已处理")

            market_context = self._load_market_context(run_time)
            qqq_metrics = market_context.get("QQQ", {})
            sector_metrics = {
                symbol: market_context[symbol]
                for symbol in MARKET_ETFS
                if symbol != "QQQ" and symbol in market_context
            }

            candidates: List[Dict[str, Any]] = []
            for raw_code in stock_codes:
                symbol = self.data_source.normalize_us_symbol(raw_code)
                try:
                    candidates.extend(self._collect_candidates(symbol, qqq_metrics, sector_metrics, summary, run_time))
                except Exception as exc:
                    logger.exception("美股盘中分析 %s 失败: %s", raw_code, exc)
                    summary.errors.append(f"{raw_code}: {exc}")

            if self._all_symbol_data_failed(summary):
                summary.status = "failed"
                raise RuntimeError("美股盘中分析失败：所有股票行情均不可用")
            review_candidates = self.signal_state_store.filter_candidates_for_review(
                "us",
                candidates,
                session_id=get_us_trading_date(run_time),
                now=run_time,
                observed_symbols=self._state_observed_symbols,
            )
            self._judge_candidates_in_batches(review_candidates, market_context, summary)
            if summary.errors or summary.warnings:
                summary.degraded = True
                summary.status = "degraded"
            return summary
        finally:
            if self.use_lock:
                release_us_intraday_running_lock(lock_token)
            summary.timings["duration_seconds"] = round(time.perf_counter() - started, 4)

    def _collect_candidates(
        self,
        symbol: str,
        qqq_metrics: Dict[str, Any],
        sector_metrics: Dict[str, Dict[str, Any]],
        summary: IntradayTaskSummary,
        run_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Fetch data, compute metrics, and return rule-matched candidates.

        Each candidate is a dict ``{"symbol", "signal_type", "metrics",
        "bars_1m"}`` to be judged later in batches by the LLM.
        """
        bars_1m = self.data_source.fetch_1m_bars(symbol, now=run_time)
        if len(bars_1m) < _MIN_BARS_FOR_SYMBOL:
            summary.skipped_symbols += 1
            _incr(summary.filter_failure_counts, "insufficient_bars")
            logger.debug("美股盘中分析跳过 %s: 1m K线不足(%s)", symbol, len(bars_1m))
            return []

        if _is_stale(bars_1m, run_time):
            summary.skipped_symbols += 1
            summary.stale_symbols += 1
            _incr(summary.filter_failure_counts, "stale_bars")
            logger.debug("美股盘中分析跳过 %s: 最新K线过旧 %s", symbol, bars_1m[-1].get("timestamp"))
            return []

        quote = self.data_source.fetch_quote(symbol)
        if quote is None:
            summary.skipped_symbols += 1
            _incr(summary.filter_failure_counts, "missing_quote")
            logger.debug("美股盘中分析跳过 %s: 缺少实时行情", symbol)
            return []

        if not qqq_metrics:
            _incr(summary.filter_failure_counts, "missing_qqq_context")

        metrics = compute_intraday_metrics(symbol, bars_1m, quote, qqq_metrics, sector_metrics, now=run_time)

        matched, failures = evaluate_signal_candidates_with_diagnostics(metrics, self.rules)
        self._state_observed_symbols.add(symbol)
        for failure in failures:
            _incr(summary.filter_failure_counts, failure)
        summary.processed_symbols += 1
        summary.candidate_count += len(matched)
        for candidate in matched:
            _incr(summary.rule_match_counts, candidate["signal_type"])
        return [
            {
                "symbol": symbol,
                "signal_type": candidate["signal_type"],
                "score": candidate.get("score"),
                "max_score": candidate.get("max_score"),
                "matched_conditions": candidate.get("matched_conditions", []),
                "failed_conditions": candidate.get("failed_conditions", []),
                "failed_condition_keys": candidate.get("failed_condition_keys", []),
                "rule_version": candidate.get("rule_version"),
                "rule_strength": candidate.get("rule_strength"),
                "severity": candidate.get("severity"),
                "category": "risk" if candidate["signal_type"] == "relative_strength_failure" else "opportunity",
                "metrics": metrics,
                "bars_1m": bars_1m,
            }
            for candidate in matched
        ]

    def _judge_candidates_in_batches(
        self,
        candidates: List[Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
        summary: IntradayTaskSummary,
    ) -> None:
        """Judge candidates in groups of ``LLM_BATCH_SIZE`` with one call each."""
        summary.llm_candidate_count = len(candidates)
        if candidates:
            market_context["market_news"] = self._get_symbol_news(
                MARKET_NEWS_SYMBOL,
                dimension="market_news",
            )
        for start in range(0, len(candidates), LLM_BATCH_SIZE):
            batch = candidates[start:start + LLM_BATCH_SIZE]
            for candidate in batch:
                candidate["news"] = self._get_symbol_news(candidate["symbol"])
            verdicts = self.llm_judge.judge_batch(batch, market_context)
            if not verdicts and batch:
                summary.warnings.append(f"LLM 未返回可用判定: batch_start={start} size={len(batch)}")
            for candidate in batch:
                verdict = verdicts.get(candidate_id(candidate["symbol"], candidate["signal_type"]))
                if verdict is None:
                    continue
                result = self._build_signal(candidate, verdict)
                if result:
                    summary.signal_results.append(result)
                    if result.notification_sent:
                        summary.notification_count += 1
                    else:
                        summary.notification_suppressed_count += 1

    def _load_market_context(self, run_time: datetime) -> Dict[str, Dict[str, Any]]:
        """
        计算大盘指数，以及板块 ETF
        """
        context: Dict[str, Dict[str, Any]] = {}
        for symbol in MARKET_ETFS.keys():
            bars_1m = self.data_source.fetch_1m_bars(symbol, now=run_time)
            if len(bars_1m) < _MIN_BARS_FOR_BENCHMARK:
                continue
            quote = self.data_source.fetch_quote(symbol)
            context[symbol] = compute_intraday_metrics(symbol, bars_1m, quote, now=run_time)
        return context

    def _get_symbol_news(
        self,
        symbol: str,
        *,
        dimension: str = "intraday_news",
    ) -> List[Dict[str, Any]]:
        cached = self._news_cache.get(symbol)
        if cached is not None:
            return cached

        if not self.news_fetcher.is_available():
            self._news_cache[symbol] = []
            return []

        stock_name = self.longbridge_fetcher.get_stock_name(symbol) or ""
        records = self.news_fetcher.fetch_and_save_news(
            symbol,
            name=stock_name,
            dimension=dimension,
            query_id=self._run_query_id,
            limit=INTRADAY_NEWS_LIMIT,
        )
        news_context = LongbridgeNewsFetcher.to_llm_context(records)
        self._news_cache[symbol] = news_context
        return news_context

    def _build_signal(
        self,
        candidate: Dict[str, Any],
        llm_result: Dict[str, Any],
    ) -> Optional[IntradaySignalResult]:
        """Turn a candidate + its LLM verdict into a reported signal result."""
        need_notification = truthy(llm_result.get("need_notification"))
        final_decision = str(llm_result.get("final_decision") or "").lower()
        if final_decision not in _NOTIFY_DECISIONS:
            need_notification = False

        signal = IntradaySignalResult(
            symbol=candidate["symbol"],
            signal_type=candidate["signal_type"],
            need_notification=need_notification,
            llm_result=llm_result,
            metrics={
                **candidate["metrics"],
                "score": candidate.get("score"),
                "max_score": candidate.get("max_score"),
                "matched_conditions": candidate.get("matched_conditions", []),
                "failed_conditions": candidate.get("failed_conditions", []),
                "rule_strength": candidate.get("rule_strength"),
                "severity": candidate.get("severity"),
                "rule_version": candidate.get("rule_version"),
                "state_signature": candidate.get("state_signature"),
                "state_transition": candidate.get("state_transition"),
                "state_generation": candidate.get("state_generation"),
            },
        )
        now = self._run_time or datetime.now(US_EASTERN)
        persist_signal = getattr(self.reporter, "persist_signal", None)
        if callable(persist_signal):
            persist_signal(signal, now)
        signal.calendar_id = self.reporter.record_to_calendar(signal)
        if need_notification:
            severity = _notification_severity(candidate)
            notification_signature = build_notification_signature(
                decision=final_decision,
                severity=severity,
                candidate_signature=str(candidate.get("state_signature") or ""),
            )
            should_notify = self.signal_state_store.should_notify(
                "us",
                symbol=signal.symbol,
                signal_type=signal.signal_type,
                notification_signature=notification_signature,
                severity=severity,
                now=now,
            )
            if should_notify:
                signal.notification_sent = self.reporter.send_notification(signal)
                if signal.notification_sent:
                    self.signal_state_store.mark_notified(
                        "us",
                        symbol=signal.symbol,
                        signal_type=signal.signal_type,
                        notification_signature=notification_signature,
                        severity=severity,
                        now=now,
                    )
        return signal

    @staticmethod
    def _all_symbol_data_failed(summary: IntradayTaskSummary) -> bool:
        if summary.total_symbols <= 0 or summary.processed_symbols > 0:
            return False
        insufficient = summary.filter_failure_counts.get("insufficient_bars", 0)
        if insufficient >= summary.total_symbols:
            return False
        data_failures = (
            summary.filter_failure_counts.get("missing_quote", 0)
            + summary.filter_failure_counts.get("stale_bars", 0)
            + len(summary.errors)
        )
        return data_failures >= summary.total_symbols


def _eastern_now(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    return current.astimezone(US_EASTERN)


def _is_stale(bars_1m: Sequence[Dict[str, Any]], now: datetime) -> bool:
    if not bars_1m:
        return False
    latest = parse_timestamp(bars_1m[-1].get("timestamp"))
    if latest is None:
        return True
    return latest + timedelta(minutes=1) < _eastern_now(now) - timedelta(seconds=STALE_BAR_SECONDS)


def _incr(counter: Dict[str, int], key: str, amount: int = 1) -> None:
    counter[key] = int(counter.get(key, 0) or 0) + amount


def _notification_severity(candidate: Dict[str, Any]) -> str:
    if candidate.get("signal_type") == "relative_strength_failure":
        return "error" if candidate.get("severity") == "high" else "warning"
    return "warning" if candidate.get("severity") == "high" else "info"



if __name__ == "__main__":
    import logging
    from finance_analysis.analysis.pipeline_config import get_pipeline_config
    logging.basicConfig(level=logging.DEBUG)
    service = USIntradayAnalysisService(config=get_pipeline_config())
    summary = service.run(["NVDA"])
    print(summary)
