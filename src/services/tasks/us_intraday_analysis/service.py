# -*- coding: utf-8 -*-
"""US intraday anomaly detection service.

This task is alert-oriented: it keeps short-lived intraday bars in Redis,
computes rule-based candidates, and asks the LLM to decide whether the signal
is worth surfacing. The orchestration here wires together the focused modules:
data fetching, caching, metric computation, rule evaluation, LLM judging and
notification delivery.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from data_provider.longbridge_fetcher import LongbridgeFetcher
from data_provider.yfinance_fetcher import YfinanceFetcher

from .cache import IntradayCache
from .config import DEFAULT_INTRADAY_SIGNAL_RULES, MARKET_ETFS
from .data_source import IntradayDataSource
from .llm import IntradayLLMJudge, truthy
from .market_calendar import get_us_trading_date, is_us_market_open
from .metrics import compute_intraday_metrics
from .models import IntradaySignalResult, IntradayTaskSummary
from .notifications import SignalReporter
from .rules import evaluate_signal_candidates

logger = logging.getLogger(__name__)

_MIN_BARS_FOR_SYMBOL = 20
_MIN_BARS_FOR_BENCHMARK = 10
_NOTIFY_DECISIONS = {"watch", "risk"}


class USIntradayAnalysisService:
    """Detects intraday anomalies on watched US symbols and alerts on them."""

    def __init__(
        self,
        *,
        config: Any,
        redis_client: Optional[Any] = None,
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        yfinance_fetcher: Optional[YfinanceFetcher] = None,
        rules: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        self.config = config
        self.cache = IntradayCache(redis_client) if redis_client is not None else IntradayCache.from_config(config)
        self.data_source = IntradayDataSource(longbridge_fetcher, yfinance_fetcher)
        self.llm_judge = IntradayLLMJudge(config)
        self.reporter = SignalReporter()
        self.rules = rules or DEFAULT_INTRADAY_SIGNAL_RULES

    def run(self, stock_codes: Sequence[str], now: Optional[datetime] = None) -> IntradayTaskSummary:
        if not is_us_market_open(now):
            return IntradayTaskSummary(market_open=False, total_symbols=len(stock_codes))

        summary = IntradayTaskSummary(market_open=True, total_symbols=len(stock_codes))
        trade_date = get_us_trading_date(now)
        market_context = self._load_market_context(trade_date)
        qqq_metrics = market_context.get("QQQ", {})
        sector_metrics = {symbol: metrics for symbol, metrics in market_context.items() if symbol != "QQQ"}

        for raw_code in stock_codes:
            symbol = self.data_source.normalize_us_symbol(raw_code)
            try:
                self._process_symbol(
                    symbol, trade_date, qqq_metrics, sector_metrics, market_context, summary
                )
            except Exception as exc:
                logger.exception("美股盘中分析 %s 失败: %s", raw_code, exc)
                summary.errors.append(f"{raw_code}: {exc}")

        return summary

    def _process_symbol(
        self,
        symbol: str,
        trade_date: str,
        qqq_metrics: Dict[str, Any],
        sector_metrics: Dict[str, Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
        summary: IntradayTaskSummary,
    ) -> None:
        bars_1m = self.data_source.fetch_1m_bars(symbol)
        if len(bars_1m) < _MIN_BARS_FOR_SYMBOL:
            summary.skipped_symbols += 1
            logger.info("美股盘中分析跳过 %s: 1m K线不足(%s)", symbol, len(bars_1m))
            return

        quote = self.data_source.fetch_quote(symbol)
        self.cache.cache_bars(symbol, trade_date, bars_1m)
        metrics = compute_intraday_metrics(symbol, bars_1m, quote, qqq_metrics, sector_metrics)
        self.cache.cache_latest(symbol, metrics, trade_date)

        candidates = evaluate_signal_candidates(metrics, self.rules)
        summary.processed_symbols += 1
        summary.candidate_count += len(candidates)
        for candidate in candidates:
            signal_type = candidate["signal_type"]
            if not self.cache.reserve_signal(symbol, signal_type):
                logger.info("美股盘中信号去重跳过: %s %s", symbol, signal_type)
                continue
            result = self._analyze_candidate(symbol, signal_type, metrics, bars_1m, market_context)
            if result:
                summary.signal_results.append(result)

    def _load_market_context(self, trade_date: str) -> Dict[str, Dict[str, Any]]:
        context: Dict[str, Dict[str, Any]] = {}
        for symbol in MARKET_ETFS:
            cached = self.cache.get_json(f"intraday:latest:US:{symbol}")
            if cached and cached.get("trade_date") == trade_date:
                context[symbol] = cached
                continue
            bars_1m = self.data_source.fetch_1m_bars(symbol)
            if len(bars_1m) < _MIN_BARS_FOR_BENCHMARK:
                continue
            quote = self.data_source.fetch_quote(symbol)
            self.cache.cache_bars(symbol, trade_date, bars_1m)
            metrics = compute_intraday_metrics(symbol, bars_1m, quote)
            self.cache.cache_latest(symbol, metrics, trade_date)
            context[symbol] = metrics
        return context

    def _analyze_candidate(
        self,
        symbol: str,
        signal_type: str,
        metrics: Dict[str, Any],
        bars_1m: Sequence[Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
    ) -> Optional[IntradaySignalResult]:
        llm_result = self.llm_judge.judge(symbol, signal_type, metrics, bars_1m, market_context)
        if llm_result is None:
            return None

        need_notification = truthy(llm_result.get("need_notification"))
        final_decision = str(llm_result.get("final_decision") or "").lower()
        if final_decision not in _NOTIFY_DECISIONS:
            need_notification = False

        signal = IntradaySignalResult(
            symbol=symbol,
            signal_type=signal_type,
            need_notification=need_notification,
            llm_result=llm_result,
            metrics=metrics,
        )
        signal.calendar_id = self.reporter.record_to_calendar(signal)
        if need_notification:
            signal.notification_sent = self.reporter.send_notification(signal)
        return signal
