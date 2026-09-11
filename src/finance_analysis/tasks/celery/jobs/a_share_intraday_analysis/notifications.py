# -*- coding: utf-8 -*-
"""Aggregated notification delivery.

A single run sends at most one aggregated notification. Per-signal dedup and
cooldown are applied before aggregation so the same code/signal is not pushed
repeatedly, while genuine state changes (e.g. sealed -> break-open) and risk
escalations can still surface immediately.
"""

from __future__ import annotations

import hashlib
import logging
import time as _time
from typing import Any, Callable, Dict, List, Optional, Sequence

from finance_analysis.notification.service import NotificationResult

from .config import (
    ASIA_SHANGHAI,
    MAX_AGGREGATED_SIGNALS,
)
from .models import AShareIntradayTaskSummary, AShareMarketSnapshot, AShareSignalResult


logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN_SECONDS = 30 * 60

# Process-level fallback guard. Redis-backed state in the service is the
# cross-worker source of truth; this also prevents duplicates inside one worker.
_COOLDOWN_STORE: Dict[str, tuple[float, int, str]] = {}

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


def reset_cooldown_store() -> None:
    """Clear the process-level cooldown store (used by tests)."""
    _COOLDOWN_STORE.clear()


def signal_dedup_key(trading_date: str, code: str, signal_type: str, phase: str) -> str:
    return f"a_share_intraday:{trading_date}:{code}:{signal_type}:{phase}"


def signal_cooldown_key(code: str, signal_type: str) -> str:
    return f"a_share_intraday:{code}:{signal_type}"


class AShareIntradayReporter:
    """Pushes one aggregated alert."""

    def __init__(
        self,
        *,
        notification_factory: Optional[Callable[[], Any]] = None,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._notification_factory = notification_factory
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or _time.time

    # ------------------------------------------------------------------
    # Dedup / cooldown
    # ------------------------------------------------------------------
    def filter_signals_for_notification(
        self,
        signals: Sequence[AShareSignalResult],
        *,
        trading_date: str,
        phase: str,
    ) -> List[AShareSignalResult]:
        """Return the subset of signals that should be notified this run."""
        selected: List[AShareSignalResult] = []
        seen_in_run: set[str] = set()
        now = self._clock()
        for signal in signals:
            if not signal.need_notification:
                continue
            dedup = signal_dedup_key(trading_date, signal.code, signal.signal_type, phase)
            if dedup in seen_in_run:
                continue
            cooldown = signal_cooldown_key(signal.code, signal.signal_type)
            generation = int(signal.metrics.get("state_generation") or 1)
            last = _COOLDOWN_STORE.get(cooldown)
            escalated = last is not None and _SEVERITY_ORDER.get(
                signal.severity,
                0,
            ) > _SEVERITY_ORDER.get(last[2], 0)
            same_generation = last is not None and last[1] == generation
            if last is not None and same_generation and not escalated and (now - last[0]) < self.cooldown_seconds:
                continue
            seen_in_run.add(dedup)
            selected.append(signal)
        return selected

    def mark_notified(self, signals: Sequence[AShareSignalResult]) -> None:
        now = self._clock()
        for signal in signals:
            generation = int(signal.metrics.get("state_generation") or 1)
            _COOLDOWN_STORE[signal_cooldown_key(signal.code, signal.signal_type)] = (
                now,
                generation,
                signal.severity,
            )

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------
    def send_aggregated_notification(
        self,
        summary: AShareIntradayTaskSummary,
        snapshot: AShareMarketSnapshot,
        signals: Sequence[AShareSignalResult],
        *,
        send_notification: bool = True,
    ) -> NotificationResult:
        if not signals:
            return NotificationResult()
        severity = self._aggregate_severity(signals)
        content = render_aggregated_notification(summary, snapshot, signals)
        service = self._build_service()
        if service is None:
            return NotificationResult()
        state_parts = sorted(
            f"{signal.code}:{signal.signal_type}:{int(signal.metrics.get('state_generation') or 1)}"
            for signal in signals
        )
        state_digest = hashlib.sha256("|".join(state_parts).encode("utf-8")).hexdigest()[:16]
        dedup = f"a_share_intraday_agg:{summary.trading_date.isoformat()}:{state_digest}"
        try:
            return service.send(
                content,
                push=send_notification,
                route_type="alert",
                severity=severity,
                dedup_key=dedup,
                cooldown_key=f"a_share_intraday_agg:{state_digest}",
            )
        except Exception as exc:
            logger.warning("发送 A 股盘中聚合通知失败: %s", exc)
            return NotificationResult()

    def _build_service(self) -> Optional[Any]:
        try:
            if self._notification_factory is not None:
                return self._notification_factory()
            from finance_analysis.notification.service import NotificationService

            return NotificationService()
        except Exception as exc:
            logger.warning("初始化通知服务失败: %s", exc)
            return None

    @staticmethod
    def _aggregate_severity(signals: Sequence[AShareSignalResult]) -> str:
        best = "info"
        for signal in signals:
            if _SEVERITY_ORDER.get(signal.severity, 0) > _SEVERITY_ORDER.get(best, 0):
                best = signal.severity
        return best


_SIGNAL_LABELS = {
    "near_limit_up_acceleration": "接近涨停加速",
    "limit_up_sealed": "涨停封板",
    "limit_up_break_open": "炸板",
    "strong_to_weak_failure": "强转弱",
    "weak_to_strong_reversal": "弱转强",
    "high_open_low_move": "高开低走",
    "abnormal_volume_breakout": "放量突破",
    "near_limit_down_risk": "接近跌停",
    "one_word_limit_up": "一字涨停",
}

_REGIME_LABELS = {
    "hot": "情绪火热",
    "active": "情绪活跃",
    "divergent": "市场分歧",
    "cold": "情绪低迷",
    "panic": "市场恐慌",
    "unknown": "状态未知",
}


def render_aggregated_notification(
    summary: AShareIntradayTaskSummary,
    snapshot: AShareMarketSnapshot,
    signals: Sequence[AShareSignalResult],
) -> str:
    header = [
        f"**A股盘中提醒 {summary.snapshot_time.astimezone(ASIA_SHANGHAI).strftime('%H:%M')}"
        f"｜{_REGIME_LABELS.get(summary.market_regime, summary.market_regime)}**",
        "",
        f"- 阶段：{summary.market_phase}",
        f"- 涨跌家数：{summary.up_count} / {summary.down_count}",
        f"- 涨停/跌停/炸板：{summary.limit_up_count} / {summary.limit_down_count} / {summary.opened_limit_up_count}",
    ]
    if snapshot.sector_leaders:
        header.append("- 领涨：" + "、".join(s.get("name", "-") for s in snapshot.sector_leaders[:3]))
    if snapshot.sector_laggers:
        header.append("- 领跌：" + "、".join(s.get("name", "-") for s in snapshot.sector_laggers[:3]))

    # Risk signals first, then opportunities.
    ordered = sorted(
        signals,
        key=lambda s: _SEVERITY_ORDER.get(s.severity, 0),
        reverse=True,
    )[:MAX_AGGREGATED_SIGNALS]
    body = ["", "重点信号："]
    for signal in ordered:
        label = _SIGNAL_LABELS.get(signal.signal_type, signal.signal_type)
        summary_text = str(signal.llm_result.get("summary", "") or "")[:80]
        marker = "⚠️" if signal.severity in ("warning", "error") else "•"
        suffix = "（AI 复核暂不可用，确定性规则生成）" if signal.fallback_used else ""
        body.append(f"{marker} {signal.code} {signal.name} {label}：{summary_text}{suffix}")
    body.append("")
    body.append("提示：A 股股票为 T+1，新增仓位隔夜无法当日卖出，请区分已持仓与未持仓情形，避免盲目追高。")
    return "\n".join(header + body)
