# -*- coding: utf-8 -*-
"""Business service for the scheduled A-share intraday analysis task.

Two-stage scan: one full-market snapshot cheaply screens a bounded candidate
pool; minute bars, fine metrics, deterministic rules and the LLM only run on
that small set. The LLM reviews rule candidates — it never scans the market.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from finance_analysis.integrations.market_data.codes import (
    is_etf_code,
    normalize_stock_code,
)
from finance_analysis.integrations.market_data.realtime_types import safe_float
from finance_analysis.market_review.trading_calendar import (
    get_a_share_market_now,
    get_a_share_market_phase,
    is_a_share_intraday_analysis_time,
    is_a_share_trading_day,
)
from finance_analysis.tasks.jobs.intraday_signal_state import (
    IntradaySignalStateStore,
    build_notification_signature,
)
from finance_analysis.tasks.lifecycle import TaskSkipped

from .config import (
    A_SHARE_INDICES,
    BOARD_BENCHMARK_INDEX,
    INDEX_CODE_ALIASES,
    LLM_BATCH_SIZE,
    MAX_LLM_CANDIDATES_PER_RUN,
    MAX_MARKET_SNAPSHOT_CANDIDATES,
    MAX_MINUTE_BAR_CANDIDATES,
    MIN_BARS_FOR_BENCHMARK,
    MIN_BARS_FOR_SYMBOL,
)
from .data_source import AShareIntradayDataSource
from .llm import AShareIntradayLLMJudge, candidate_id
from .lock import (
    release_a_share_intraday_lock,
    try_acquire_a_share_intraday_lock,
)
from .metrics import _change_over_minutes, compute_a_share_intraday_metrics
from .models import (
    AShareCandidate,
    AShareIntradayTaskSummary,
    AShareMarketSnapshot,
    AShareSignalResult,
)
from .notifications import AShareIntradayReporter
from .price_limits import (
    BOARD_CONVERTIBLE_BOND,
    BOARD_ETF,
    classify_a_share_board,
    resolve_price_limit_rule,
)
from .rules import (
    DEFAULT_A_SHARE_INTRADAY_SIGNAL_RULES,
    FALLBACK_RISK_SIGNALS,
    SIGNAL_CATEGORY,
    SIGNAL_SEVERITY,
    SignalRule,
    evaluate_signal_candidates,
)

logger = logging.getLogger(__name__)

_NOTIFY_DECISIONS = {"watch", "risk"}
# Boards excluded from limit-statistics and stock-sentiment counts.
_NON_STOCK_BOARDS = {BOARD_ETF, BOARD_CONVERTIBLE_BOND}


class AShareIntradayAnalysisService:
    """Detects A-share intraday anomalies and surfaces the important ones."""

    def __init__(
        self,
        *,
        config: Any = None,
        data_source: Optional[AShareIntradayDataSource] = None,
        llm_judge: Optional[AShareIntradayLLMJudge] = None,
        reporter: Optional[AShareIntradayReporter] = None,
        watchlist_provider: Optional[Callable[[], Sequence[str]]] = None,
        rules: Optional[Sequence[SignalRule]] = None,
        use_lock: bool = True,
        signal_state_store: Optional[IntradaySignalStateStore] = None,
    ) -> None:
        self.config = config
        self.data_source = data_source or AShareIntradayDataSource()
        self.llm_judge = llm_judge or AShareIntradayLLMJudge(config)
        self.reporter = reporter or AShareIntradayReporter()
        self.watchlist_provider = watchlist_provider
        self.rules: Sequence[SignalRule] = (
            rules if rules is not None else DEFAULT_A_SHARE_INTRADAY_SIGNAL_RULES
        )
        self.use_lock = use_lock
        self.signal_state_store = signal_state_store or IntradaySignalStateStore()
        self._benchmark_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._state_observed_symbols: set[str] = set()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(
        self,
        *,
        now: Optional[datetime] = None,
        send_notification: bool = True,
    ) -> AShareIntradayTaskSummary:
        run_time = get_a_share_market_now(now)
        self._validate_trading_day_and_session(run_time)

        trading_date = run_time.date()
        phase = get_a_share_market_phase(run_time)
        summary = AShareIntradayTaskSummary(
            trading_date=trading_date,
            snapshot_time=run_time,
            market_phase=phase,
            market_open=True,
        )

        lock_key = f"a_share_intraday:{trading_date.isoformat()}:{run_time.strftime('%H:%M')}"
        lock_token = try_acquire_a_share_intraday_lock(lock_key) if self.use_lock else object()
        if lock_token is None:
            raise TaskSkipped("已有 A 股盘中分析任务正在执行")

        timings: Dict[str, Any] = {"external_api_calls": 0, "llm_calls": 0}
        total_start = _time.time()
        try:
            self._benchmark_cache = {}
            self._state_observed_symbols = set()
            rows = self._load_snapshot_rows(summary, timings)
            if not rows:
                raise RuntimeError("A 股全市场实时快照获取失败")

            market_snapshot = self._build_market_snapshot(rows, trading_date, run_time, phase, summary, timings)
            summary.market_regime = market_snapshot.market_regime

            watchlist = self._load_watchlist()
            summary.watchlist_symbols = len(watchlist)

            candidates = self._build_candidates(rows, watchlist, trading_date)
            summary.snapshot_candidate_count = len(candidates)

            rule_candidates = self._evaluate_candidates(
                candidates, market_snapshot, trading_date, run_time, phase, summary, timings
            )
            summary.rule_candidate_count = len(rule_candidates)

            review_candidates = self.signal_state_store.filter_candidates_for_review(
                "cn",
                rule_candidates,
                session_id=trading_date.isoformat(),
                now=run_time,
                observed_symbols=self._state_observed_symbols,
            )
            verdicts = self._judge(review_candidates, market_snapshot, summary, timings)
            signals = self._build_signal_results(review_candidates, verdicts, phase)
            summary.signal_results = signals

            self._report(summary, market_snapshot, signals, send_notification)
        finally:
            if self.use_lock:
                release_a_share_intraday_lock(lock_token)
            timings["total_seconds"] = round(_time.time() - total_start, 3)
            summary.timings = timings

        logger.info(
            "A股盘中分析完成: phase=%s regime=%s snapshot=%s candidates=%s rule=%s llm=%s notify=%s",
            phase,
            summary.market_regime,
            summary.total_market_symbols,
            summary.snapshot_candidate_count,
            summary.rule_candidate_count,
            summary.llm_candidate_count,
            summary.notification_count,
        )
        return summary

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_trading_day_and_session(self, now: datetime) -> None:
        if now.weekday() >= 5:
            raise TaskSkipped("周末非 A 股交易日")
        if not is_a_share_trading_day(now.date(), now):
            raise TaskSkipped("当天为 A 股休市日")
        if not is_a_share_intraday_analysis_time(now):
            raise TaskSkipped("当前不在 A 股有效盘中分析时段")

    # ------------------------------------------------------------------
    # Market snapshot
    # ------------------------------------------------------------------
    def _load_snapshot_rows(
        self,
        summary: AShareIntradayTaskSummary,
        timings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        start = _time.time()
        rows = self.data_source.get_market_snapshot_rows()
        timings["snapshot_fetch_seconds"] = round(_time.time() - start, 3)
        timings["external_api_calls"] += 1
        summary.total_market_symbols = len(rows)
        return rows

    def _build_market_snapshot(
        self,
        rows: Sequence[Dict[str, Any]],
        trading_date: date,
        run_time: datetime,
        phase: str,
        summary: AShareIntradayTaskSummary,
        timings: Dict[str, Any],
    ) -> AShareMarketSnapshot:
        warnings: List[str] = []
        breadth = compute_market_breadth(rows, trading_date)
        summary.up_count = breadth["up_count"]
        summary.down_count = breadth["down_count"]
        summary.limit_up_count = breadth["limit_up_count"]
        summary.limit_down_count = breadth["limit_down_count"]
        summary.opened_limit_up_count = breadth["opened_from_limit_up_count"]

        indices = self._load_indices(warnings, timings)
        sector_leaders, sector_laggers = self._load_sectors(warnings, timings)

        regime = determine_market_regime(breadth, indices, sector_leaders, sector_laggers)
        sentiment = compute_sentiment_score(breadth)

        summary.warnings.extend(warnings)
        snapshot = AShareMarketSnapshot(
            trading_date=trading_date,
            snapshot_time=run_time,
            market_phase=phase,
            indices=indices,
            market_stats=breadth,
            sector_leaders=sector_leaders,
            sector_laggers=sector_laggers,
            market_regime=regime,
            sentiment_score=sentiment,
            warnings=warnings,
        )
        return snapshot

    def _load_indices(
        self,
        warnings: List[str],
        timings: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw = self.data_source.get_main_indices()
        timings["external_api_calls"] += 1
        if not raw:
            warnings.append("主要指数行情获取失败，已降级")
            return {}
        indices: Dict[str, Any] = {}
        for item in raw:
            code = str(item.get("code") or "").strip().lower()
            canonical = INDEX_CODE_ALIASES.get(code, code.lstrip("shszbj"))
            name = item.get("name") or A_SHARE_INDICES.get(canonical, canonical)
            indices[canonical] = {
                "name": name,
                "change_pct": safe_float(item.get("change_pct")),
                "current": safe_float(item.get("current")),
                "amount": safe_float(item.get("amount")),
            }
        return indices

    def _load_sectors(
        self,
        warnings: List[str],
        timings: Dict[str, Any],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        top, bottom = self.data_source.get_sector_rankings(5)
        timings["external_api_calls"] += 1
        if not top and not bottom:
            warnings.append("板块排行获取失败，已降级")
        return list(top), list(bottom)

    # ------------------------------------------------------------------
    # Candidate construction
    # ------------------------------------------------------------------
    def _load_watchlist(self) -> List[str]:
        if self.watchlist_provider is not None:
            raw = self.watchlist_provider()
        else:
            from finance_analysis.database.repositories.watch_list import (
                get_watch_list_codes_by_market,
            )

            raw = get_watch_list_codes_by_market("CN")
        codes = [normalize_stock_code(str(code)) for code in raw or []]
        return [code for code in dict.fromkeys(codes) if code]

    def _build_candidates(
        self,
        rows: Sequence[Dict[str, Any]],
        watchlist: Sequence[str],
        trading_date: date,
    ) -> List[AShareCandidate]:
        rows_by_code = {normalize_stock_code(str(row.get("code"))): row for row in rows}
        candidates: Dict[str, AShareCandidate] = {}

        # 1. Watchlist always enters the first stage.
        for code in watchlist:
            row = rows_by_code.get(code, {})
            name = str(row.get("name") or "")
            board = classify_a_share_board(code, name, today=trading_date)
            candidates[code] = AShareCandidate(
                code=code,
                name=name,
                board=board,
                origin="watchlist",
                reason="自选股",
                priority=_origin_priority("watchlist"),
                snapshot=row,
            )

        # 2. Market-wide rule candidates from the cheap snapshot.
        market_hits = screen_snapshot_candidates(rows, trading_date)
        for code, row, reason in market_hits:
            if code in candidates:
                continue
            name = str(row.get("name") or "")
            board = classify_a_share_board(code, name, today=trading_date)
            candidates[code] = AShareCandidate(
                code=code,
                name=name,
                board=board,
                origin="market_rule",
                reason=reason,
                priority=_origin_priority("market_rule"),
                snapshot=row,
            )
            if len(candidates) >= MAX_MARKET_SNAPSHOT_CANDIDATES * 2:
                break

        # 3. Sector-leader proxy: strongest movers by turnover among the rest.
        for code, row, reason in screen_sector_leaders(rows, trading_date, set(candidates)):
            if code in candidates:
                continue
            name = str(row.get("name") or "")
            board = classify_a_share_board(code, name, today=trading_date)
            candidates[code] = AShareCandidate(
                code=code,
                name=name,
                board=board,
                origin="sector_leader",
                reason=reason,
                priority=_origin_priority("sector_leader"),
                snapshot=row,
            )

        ordered = sorted(candidates.values(), key=lambda c: (-c.priority, c.code))
        return ordered[:MAX_MARKET_SNAPSHOT_CANDIDATES]

    # ------------------------------------------------------------------
    # Minute-bar + rule stage
    # ------------------------------------------------------------------
    def _evaluate_candidates(
        self,
        candidates: Sequence[AShareCandidate],
        snapshot: AShareMarketSnapshot,
        trading_date: date,
        run_time: datetime,
        phase: str,
        summary: AShareIntradayTaskSummary,
        timings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        rule_candidates: List[Dict[str, Any]] = []
        processed = 0
        start = _time.time()
        for candidate in candidates:
            if processed >= MAX_MINUTE_BAR_CANDIDATES:
                break
            if candidate.board in (BOARD_ETF, BOARD_CONVERTIBLE_BOND):
                # ETFs/CBs act only as benchmarks here, not stock signals.
                continue
            try:
                hits = self._evaluate_single(
                    candidate, snapshot, trading_date, run_time, phase, summary, timings
                )
            except Exception as exc:
                logger.warning("A股盘中分析 %s 失败: %s", candidate.code, exc, exc_info=True)
                summary.errors.append(f"{candidate.code}: {exc}")
                continue
            processed += 1
            rule_candidates.extend(hits)
        timings["minute_fetch_seconds"] = round(_time.time() - start, 3)
        summary.minute_candidate_count = processed
        return rule_candidates

    def _evaluate_single(
        self,
        candidate: AShareCandidate,
        snapshot: AShareMarketSnapshot,
        trading_date: date,
        run_time: datetime,
        phase: str,
        summary: AShareIntradayTaskSummary,
        timings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        bars = self.data_source.fetch_minute_bars(candidate.code, now=run_time)
        timings["external_api_calls"] += 1
        if len(bars) < MIN_BARS_FOR_SYMBOL:
            summary.warnings.append(f"{candidate.code} 分钟K线不足({len(bars)})，跳过")
            return []

        quote = self.data_source.get_quote(candidate.code)
        timings["external_api_calls"] += 1
        snapshot_row = candidate.snapshot or {}
        pre_close = safe_float(snapshot_row.get("pre_close"))
        if pre_close is None and quote is not None:
            pre_close = safe_float(getattr(quote, "pre_close", None))

        price_limit = resolve_price_limit_rule(
            code=candidate.code,
            name=candidate.name,
            pre_close=pre_close,
            quote=quote,
            today=trading_date,
        )

        main_metrics = self._benchmark_metrics(BOARD_BENCHMARK_INDEX.get("main_board", "000300"), run_time, timings)
        board_index = BOARD_BENCHMARK_INDEX.get(candidate.board, "000001")
        board_metrics = self._benchmark_metrics(board_index, run_time, timings)

        metrics = compute_a_share_intraday_metrics(
            code=candidate.code,
            name=candidate.name,
            board=candidate.board,
            bars_1m=bars,
            quote=quote,
            snapshot=snapshot_row,
            price_limit=price_limit,
            main_index_metrics=main_metrics,
            board_index_metrics=board_metrics,
            sector_change_15m=None,
            data_source="efinance",
        )

        matched = evaluate_signal_candidates(metrics, phase, self.rules)
        self._state_observed_symbols.add(candidate.code)
        return [
            {
                "id": candidate_id(candidate.code, item["signal_type"]),
                "code": candidate.code,
                "name": candidate.name,
                "board": candidate.board,
                "signal_type": item["signal_type"],
                "category": SIGNAL_CATEGORY.get(item["signal_type"], "info"),
                "severity": SIGNAL_SEVERITY.get(item["signal_type"], "info"),
                "market_phase": phase,
                "metrics": metrics,
                "recent_bars": _recent_bars_payload(bars),
                "announcements": [],
                "recent_news": [],
            }
            for item in matched
        ]

    def _benchmark_metrics(
        self,
        index_code: str,
        run_time: datetime,
        timings: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if index_code in self._benchmark_cache:
            return self._benchmark_cache[index_code]
        bars = self.data_source.fetch_minute_bars(index_code, now=run_time)
        timings["external_api_calls"] += 1
        if len(bars) < MIN_BARS_FOR_BENCHMARK:
            self._benchmark_cache[index_code] = None
            return None
        metrics = {"change_15m": _change_over_minutes(bars, 15)}
        self._benchmark_cache[index_code] = metrics
        return metrics

    # ------------------------------------------------------------------
    # LLM + signals
    # ------------------------------------------------------------------
    def _judge(
        self,
        rule_candidates: List[Dict[str, Any]],
        snapshot: AShareMarketSnapshot,
        summary: AShareIntradayTaskSummary,
        timings: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        if not rule_candidates:
            return {}
        prioritized = sorted(
            rule_candidates,
            key=lambda c: _signal_priority(c["signal_type"]),
            reverse=True,
        )[:MAX_LLM_CANDIDATES_PER_RUN]
        summary.llm_candidate_count = len(prioritized)

        market_context = snapshot.to_context_dict()
        start = _time.time()
        verdicts: Dict[str, Dict[str, Any]] = {}
        for offset in range(0, len(prioritized), LLM_BATCH_SIZE):
            batch = prioritized[offset:offset + LLM_BATCH_SIZE]
            timings["llm_calls"] += 1
            verdicts.update(self.llm_judge.judge_batch(batch, market_context))
        timings["llm_seconds"] = round(_time.time() - start, 3)
        return verdicts

    def _build_signal_results(
        self,
        rule_candidates: Sequence[Dict[str, Any]],
        verdicts: Dict[str, Dict[str, Any]],
        phase: str,
    ) -> List[AShareSignalResult]:
        results: List[AShareSignalResult] = []
        seen: set[str] = set()
        for candidate in rule_candidates:
            cid = candidate["id"]
            if cid in seen:
                continue
            seen.add(cid)
            verdict = verdicts.get(cid)
            if verdict is not None:
                signal = self._signal_from_verdict(candidate, verdict)
            else:
                signal = self._signal_from_fallback(candidate)
            if signal is not None:
                results.append(signal)
        return results

    def _signal_from_verdict(
        self,
        candidate: Dict[str, Any],
        verdict: Dict[str, Any],
    ) -> AShareSignalResult:
        decision = str(verdict.get("final_decision") or "ignore").lower()
        need = bool(verdict.get("need_notification")) and decision in _NOTIFY_DECISIONS
        severity = self._resolve_severity(candidate["signal_type"], decision)
        return AShareSignalResult(
            code=candidate["code"],
            name=candidate["name"],
            signal_type=candidate["signal_type"],
            board=candidate["board"],
            need_notification=need,
            final_decision=decision,
            metrics=_signal_metrics(candidate),
            llm_result=verdict,
            severity=severity,
        )

    def _signal_from_fallback(self, candidate: Dict[str, Any]) -> Optional[AShareSignalResult]:
        signal_type = candidate["signal_type"]
        is_risk = signal_type in FALLBACK_RISK_SIGNALS
        severity = self._resolve_severity(signal_type, "risk" if is_risk else "watch")
        fallback_result = {
            "final_decision": "risk" if is_risk else "watch",
            "direction": "bearish" if is_risk else "neutral",
            "need_notification": is_risk,
            "confidence": 0.0,
            "driver_type": "unknown",
            "signal_quality": "low",
            "summary": "AI 复核暂不可用，本提示由确定性量价规则生成",
            "reason": "规则命中但 LLM 复核不可用",
            "risk": "无 AI 复核，请谨慎对待",
            "holder_suggestion": "已持仓者关注是否跌破 VWAP 或再次炸板",
            "observer_suggestion": "未持仓者避免在接近涨停时盲目追高",
            "t1_warning": "A 股股票 T+1，新增仓位隔夜无法当日卖出",
            "invalidation": "价格重新站上/跌破关键位则信号失效",
        }
        # Opportunity signals without LLM review are recorded but not high-priority alerted.
        return AShareSignalResult(
            code=candidate["code"],
            name=candidate["name"],
            signal_type=signal_type,
            board=candidate["board"],
            need_notification=is_risk,
            final_decision="risk" if is_risk else "watch",
            metrics=_signal_metrics(candidate),
            llm_result=fallback_result,
            severity=severity if is_risk else "info",
            fallback_used=True,
        )

    def _resolve_severity(self, signal_type: str, decision: str) -> str:
        base = SIGNAL_SEVERITY.get(signal_type, "info")
        if decision == "risk" and base == "info":
            return "warning"
        return base

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _report(
        self,
        summary: AShareIntradayTaskSummary,
        snapshot: AShareMarketSnapshot,
        signals: Sequence[AShareSignalResult],
        send_notification: bool,
    ) -> None:
        summary.calendar_id = self.reporter.record_summary(summary, snapshot)

        state_selected = [
            signal
            for signal in signals
            if self._should_notify_state_change(signal, summary.snapshot_time)
        ]
        to_notify = self.reporter.filter_signals_for_notification(
            state_selected,
            trading_date=summary.trading_date.isoformat(),
            phase=summary.market_phase,
        )
        notified = False
        if to_notify:
            notified = self.reporter.send_aggregated_notification(
                summary, snapshot, to_notify, send_notification=send_notification
            )
            if notified:
                self.reporter.mark_notified(to_notify)
                for signal in to_notify:
                    self._mark_notification_state(signal, summary.snapshot_time)
                summary.notification_count = len(to_notify)

        # Per-signal calendar entries for notified or high-risk signals.
        important = [
            s for s in signals
            if s in to_notify or s.severity in ("warning", "error")
        ]
        for signal in important:
            signal.notification_sent = notified and signal in to_notify
            signal.calendar_id = self.reporter.record_signal(signal, summary.snapshot_time)

    def _should_notify_state_change(self, signal: AShareSignalResult, now: datetime) -> bool:
        if not signal.need_notification:
            return False
        signature = self._notification_signature(signal)
        return self.signal_state_store.should_notify(
            "cn",
            symbol=signal.code,
            signal_type=signal.signal_type,
            notification_signature=signature,
            severity=signal.severity,
            now=now,
        )

    def _mark_notification_state(self, signal: AShareSignalResult, now: datetime) -> None:
        self.signal_state_store.mark_notified(
            "cn",
            symbol=signal.code,
            signal_type=signal.signal_type,
            notification_signature=self._notification_signature(signal),
            severity=signal.severity,
            now=now,
        )

    @staticmethod
    def _notification_signature(signal: AShareSignalResult) -> str:
        return build_notification_signature(
            decision=signal.final_decision,
            severity=signal.severity,
            candidate_signature=str(signal.metrics.get("state_signature") or ""),
        )


# ----------------------------------------------------------------------
# Module-level deterministic helpers
# ----------------------------------------------------------------------
def _origin_priority(origin: str) -> int:
    return {"watchlist": 30, "market_rule": 20, "sector_leader": 10}.get(origin, 0)


def _signal_priority(signal_type: str) -> int:
    category = SIGNAL_CATEGORY.get(signal_type, "info")
    return {"risk": 3, "opportunity": 2, "info": 1}.get(category, 0)


def _recent_bars_payload(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    from .bars import aggregate_bars

    return {
        "bars_1m_tail": list(bars[-30:]),
        "bars_5m_tail": aggregate_bars(bars, 5)[-12:],
        "bars_15m_tail": aggregate_bars(bars, 15)[-8:],
    }


def _signal_metrics(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **candidate["metrics"],
        "state_signature": candidate.get("state_signature"),
        "state_transition": candidate.get("state_transition"),
        "state_generation": candidate.get("state_generation"),
    }


def _limit_ratio_for_row(code: str, name: str) -> Optional[float]:
    from .price_limits import _limit_ratio_for, _structural_board, is_risk_warning

    structural = _structural_board(code)
    return _limit_ratio_for(structural, is_risk_warning(name))


def compute_market_breadth(rows: Sequence[Dict[str, Any]], trading_date: date) -> Dict[str, Any]:
    """Compute deterministic market breadth from the full-market snapshot."""
    up = down = flat = 0
    limit_up = limit_down = 0
    touched_up = opened_up = 0
    touched_down = 0
    up5 = down5 = 0
    high_open_low = 0
    total_amount = 0.0
    counted = 0

    for row in rows:
        code = normalize_stock_code(str(row.get("code") or ""))
        name = str(row.get("name") or "")
        if not code or is_etf_code(code):
            continue
        price = safe_float(row.get("price"))
        pre_close = safe_float(row.get("pre_close"))
        amount = safe_float(row.get("amount"))
        change_pct = safe_float(row.get("change_pct"))
        if amount is not None:
            total_amount += amount
        if price is None or pre_close is None or price <= 0 or pre_close <= 0:
            continue
        counted += 1
        if price > pre_close:
            up += 1
        elif price < pre_close:
            down += 1
        else:
            flat += 1
        if change_pct is not None:
            if change_pct >= 5:
                up5 += 1
            elif change_pct <= -5:
                down5 += 1

        ratio = _limit_ratio_for_row(code, name)
        if ratio is None:
            continue
        limit_up_price = round(pre_close * (1 + ratio), 2)
        limit_down_price = round(pre_close * (1 - ratio), 2)
        high = safe_float(row.get("high"))
        low = safe_float(row.get("low"))
        open_price = safe_float(row.get("open"))
        is_lu = abs(price - limit_up_price) / limit_up_price * 100 <= 0.05
        is_ld = abs(price - limit_down_price) / limit_down_price * 100 <= 0.05
        if is_lu:
            limit_up += 1
        if is_ld:
            limit_down += 1
        if high is not None and high >= limit_up_price - 0.005:
            touched_up += 1
            if not is_lu:
                opened_up += 1
        if low is not None and low <= limit_down_price + 0.005:
            touched_down += 1
        if (
            open_price is not None
            and open_price > pre_close * 1.015
            and price < open_price * 0.99
        ):
            high_open_low += 1

    break_rate = (opened_up / touched_up) if touched_up > 0 else None
    return {
        "counted_symbols": counted,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "touched_limit_up_count": touched_up,
        "opened_from_limit_up_count": opened_up,
        "touched_limit_down_count": touched_down,
        "up_over_5_count": up5,
        "down_over_5_count": down5,
        "high_open_low_count": high_open_low,
        "break_rate": break_rate,
        "total_amount": round(total_amount / 1e8, 4) if total_amount else 0.0,
        "up_ratio": round(up / counted, 4) if counted else None,
        "down_ratio": round(down / counted, 4) if counted else None,
    }


def determine_market_regime(
    breadth: Dict[str, Any],
    indices: Dict[str, Any],
    sector_leaders: Sequence[Dict[str, Any]],
    sector_laggers: Sequence[Dict[str, Any]],
) -> str:
    """Deterministic market-regime classification; the LLM only explains it."""
    counted = breadth.get("counted_symbols") or 0
    if counted < 50:
        return "unknown"
    limit_up = breadth.get("limit_up_count", 0)
    limit_down = breadth.get("limit_down_count", 0)
    break_rate = breadth.get("break_rate")
    up_ratio = breadth.get("up_ratio") or 0.0

    index_changes = [
        v.get("change_pct") for v in indices.values() if isinstance(v, dict) and v.get("change_pct") is not None
    ]
    index_up = sum(1 for c in index_changes if c > 0)
    index_resonance = bool(index_changes) and index_up == len(index_changes)
    strong_sectors = sum(1 for s in sector_leaders if (s.get("change_pct") or 0) > 1.5)

    if limit_down >= max(20, limit_up * 2) and up_ratio < 0.3:
        return "panic"
    if up_ratio >= 0.65 and limit_up >= 30 and index_resonance and (break_rate is None or break_rate < 0.4):
        return "hot"
    if up_ratio >= 0.55 and limit_up >= 15 and strong_sectors >= 2:
        return "active"
    if break_rate is not None and break_rate >= 0.5 and limit_up >= 10:
        return "divergent"
    if 0.4 <= up_ratio <= 0.6:
        return "divergent"
    if up_ratio < 0.4:
        return "cold"
    return "active"


def compute_sentiment_score(breadth: Dict[str, Any]) -> Optional[float]:
    counted = breadth.get("counted_symbols") or 0
    if counted < 50:
        return None
    up_ratio = breadth.get("up_ratio") or 0.0
    limit_up = breadth.get("limit_up_count", 0)
    limit_down = breadth.get("limit_down_count", 0)
    break_rate = breadth.get("break_rate") or 0.0
    score = up_ratio * 60
    score += min(limit_up, 80) / 80 * 25
    score -= min(limit_down, 80) / 80 * 25
    score -= break_rate * 15
    return round(max(0.0, min(100.0, score + 20)), 2)


def screen_snapshot_candidates(
    rows: Sequence[Dict[str, Any]],
    trading_date: date,
) -> List[tuple[str, Dict[str, Any], str]]:
    """Cheap snapshot-only screening for anomalous candidates."""
    hits: List[tuple[float, str, Dict[str, Any], str]] = []
    for row in rows:
        code = normalize_stock_code(str(row.get("code") or ""))
        name = str(row.get("name") or "")
        if not code or is_etf_code(code):
            continue
        price = safe_float(row.get("price"))
        pre_close = safe_float(row.get("pre_close"))
        change_pct = safe_float(row.get("change_pct"))
        amount = safe_float(row.get("amount"))
        amplitude = safe_float(row.get("amplitude"))
        turnover = safe_float(row.get("turnover_rate"))
        open_price = safe_float(row.get("open"))
        high = safe_float(row.get("high"))
        if price is None or pre_close is None or pre_close <= 0:
            continue

        ratio = _limit_ratio_for_row(code, name)
        reasons: List[str] = []
        score = 0.0
        if ratio is not None:
            limit_up_price = round(pre_close * (1 + ratio), 2)
            limit_down_price = round(pre_close * (1 - ratio), 2)
            dist_up = (limit_up_price - price) / limit_up_price * 100 if limit_up_price else None
            dist_down = (price - limit_down_price) / limit_down_price * 100 if limit_down_price else None
            if dist_up is not None and 0 < dist_up <= 2.0 and (change_pct or 0) > 0:
                reasons.append("接近涨停")
                score += 8
            if high is not None and high >= limit_up_price - 0.005 and abs(price - limit_up_price) / limit_up_price * 100 > 0.05:
                reasons.append("炸板")
                score += 9
            if dist_down is not None and 0 <= dist_down <= 2.0:
                reasons.append("接近跌停")
                score += 9
        if change_pct is not None and abs(change_pct) >= 6:
            reasons.append("大幅波动")
            score += abs(change_pct) / 2
        if open_price is not None and open_price > pre_close * 1.02 and price < open_price * 0.985:
            reasons.append("高开低走")
            score += 6
        if amplitude is not None and amplitude >= 8:
            reasons.append("振幅异常")
            score += 4
        if turnover is not None and turnover >= 15:
            reasons.append("换手异常")
            score += 4
        if amount is not None and amount >= 1.5e9:
            score += 2

        if reasons:
            hits.append((score, code, row, "/".join(dict.fromkeys(reasons))))

    hits.sort(key=lambda item: item[0], reverse=True)
    return [(code, row, reason) for _, code, row, reason in hits[: MAX_MARKET_SNAPSHOT_CANDIDATES]]


def screen_sector_leaders(
    rows: Sequence[Dict[str, Any]],
    trading_date: date,
    exclude: set[str],
) -> List[tuple[str, Dict[str, Any], str]]:
    """Proxy for strong-sector leaders: top movers by turnover among gainers."""
    pool: List[tuple[float, str, Dict[str, Any]]] = []
    for row in rows:
        code = normalize_stock_code(str(row.get("code") or ""))
        if not code or code in exclude or is_etf_code(code):
            continue
        change_pct = safe_float(row.get("change_pct"))
        amount = safe_float(row.get("amount"))
        if change_pct is None or change_pct < 3 or amount is None:
            continue
        pool.append((amount, code, row))
    pool.sort(key=lambda item: item[0], reverse=True)
    return [(code, row, "强势龙头候选") for _, code, row in pool[:10]]
