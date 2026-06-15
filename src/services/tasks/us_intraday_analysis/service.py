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
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from data_provider.longbridge_fetcher import LongbridgeFetcher
from data_provider.yfinance_fetcher import YfinanceFetcher

from .config import LLM_BATCH_SIZE, MARKET_ETFS
from .data_source import IntradayDataSource
from .llm import IntradayLLMJudge, candidate_id, truthy
from .metrics import compute_intraday_metrics
from .models import IntradaySignalResult, IntradayTaskSummary
from .notifications import SignalReporter
from .rules import DEFAULT_INTRADAY_SIGNAL_RULES, RulePredicate, evaluate_signal_candidates

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
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        yfinance_fetcher: Optional[YfinanceFetcher] = None,
        rules: Optional[Sequence[RulePredicate]] = None,
    ) -> None:
        self.config = config
        self.data_source = IntradayDataSource(longbridge_fetcher, yfinance_fetcher)
        self.llm_judge = IntradayLLMJudge(config)
        self.reporter = SignalReporter()
        self.rules: Sequence[RulePredicate] = rules if rules is not None else DEFAULT_INTRADAY_SIGNAL_RULES

    def run(self, stock_codes: Sequence[str], now: Optional[datetime] = None) -> IntradayTaskSummary:
        # if not is_us_market_open(now):
        #     return IntradayTaskSummary(market_open=False, total_symbols=len(stock_codes))

        summary = IntradayTaskSummary(market_open=True, total_symbols=len(stock_codes))
        market_context = self._load_market_context()
        qqq_metrics = market_context.get("QQQ", {})
        sector_metrics = {symbol: metrics for symbol, metrics in market_context.items() if symbol != "QQQ"}

        candidates: List[Dict[str, Any]] = []
        for raw_code in stock_codes:
            symbol = self.data_source.normalize_us_symbol(raw_code)
            try:
                candidates.extend(self._collect_candidates(symbol, qqq_metrics, sector_metrics, summary))
            except Exception as exc:
                logger.exception("美股盘中分析 %s 失败: %s", raw_code, exc)
                summary.errors.append(f"{raw_code}: {exc}")

        self._judge_candidates_in_batches(candidates, market_context, summary)
        return summary

    def _collect_candidates(
        self,
        symbol: str,
        qqq_metrics: Dict[str, Any],
        sector_metrics: Dict[str, Dict[str, Any]],
        summary: IntradayTaskSummary,
    ) -> List[Dict[str, Any]]:
        """Fetch data, compute metrics, and return rule-matched candidates.

        Each candidate is a dict ``{"symbol", "signal_type", "metrics",
        "bars_1m"}`` to be judged later in batches by the LLM.
        """
        bars_1m = self.data_source.fetch_1m_bars(symbol)
        if len(bars_1m) < _MIN_BARS_FOR_SYMBOL:
            summary.skipped_symbols += 1
            logger.info("美股盘中分析跳过 %s: 1m K线不足(%s)", symbol, len(bars_1m))
            return []

        quote = self.data_source.fetch_quote(symbol)
        metrics = compute_intraday_metrics(symbol, bars_1m, quote, qqq_metrics, sector_metrics)

        matched = evaluate_signal_candidates(metrics, self.rules)
        summary.processed_symbols += 1
        summary.candidate_count += len(matched)
        return [
            {
                "symbol": symbol,
                "signal_type": candidate["signal_type"],
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
        for start in range(0, len(candidates), LLM_BATCH_SIZE):
            batch = candidates[start:start + LLM_BATCH_SIZE]
            verdicts = self.llm_judge.judge_batch(batch, market_context)
            for candidate in batch:
                verdict = verdicts.get(candidate_id(candidate["symbol"], candidate["signal_type"]))
                if verdict is None:
                    continue
                result = self._build_signal(candidate, verdict)
                if result:
                    summary.signal_results.append(result)

    def _load_market_context(self) -> Dict[str, Dict[str, Any]]:
        """
        计算大盘指数，以及板块 ETF
        """
        context: Dict[str, Dict[str, Any]] = {}
        for symbol in MARKET_ETFS.keys():
            bars_1m = self.data_source.fetch_1m_bars(symbol)
            if len(bars_1m) < _MIN_BARS_FOR_BENCHMARK:
                continue
            quote = self.data_source.fetch_quote(symbol)
            context[symbol] = compute_intraday_metrics(symbol, bars_1m, quote)
        return context

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
            metrics=candidate["metrics"],
        )
        signal.calendar_id = self.reporter.record_to_calendar(signal)
        if need_notification:
            signal.notification_sent = self.reporter.send_notification(signal)
        return signal



if __name__ == "__main__":
    import logging
    from src.config import get_config
    logging.basicConfig(level=logging.DEBUG)
    service = USIntradayAnalysisService(config=get_config())
    summary = service.run(["NVDA"])
    print(summary)