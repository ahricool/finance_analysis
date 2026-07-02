# -*- coding: utf-8 -*-
"""Calendar persistence and aggregated notification delivery.

A single run sends at most one aggregated notification. Per-signal dedup and
cooldown are applied before aggregation so the same code/signal is not pushed
repeatedly, while genuine state changes (e.g. sealed -> break-open) and risk
escalations can still surface immediately.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time as _time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from .config import (
    A_SHARE_INTRADAY_SIGNAL_CALENDAR_TYPE,
    A_SHARE_INTRADAY_SUMMARY_CALENDAR_TYPE,
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
    """Persists signals to the calendar and pushes one aggregated alert."""

    def __init__(
        self,
        *,
        notification_factory: Optional[Callable[[], Any]] = None,
        calendar_writer: Optional[Callable[..., Optional[int]]] = None,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._notification_factory = notification_factory
        self._calendar_writer = calendar_writer
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
    # Calendar
    # ------------------------------------------------------------------
    def record_summary(
        self,
        summary: AShareIntradayTaskSummary,
        snapshot: AShareMarketSnapshot,
    ) -> Optional[int]:
        title = self._summary_title(summary)
        content = render_summary_content(summary, snapshot)
        return self._write_calendar(
            time=summary.snapshot_time,
            title=title,
            content=content,
            calendar_type=A_SHARE_INTRADAY_SUMMARY_CALENDAR_TYPE,
        )

    def record_signal(self, signal: AShareSignalResult, snapshot_time: datetime) -> Optional[int]:
        title = f"A股盘中异动：{signal.code} {signal.name} {self._signal_label(signal.signal_type)}"
        content = render_signal_content(signal)
        return self._write_calendar(
            time=snapshot_time,
            title=title,
            content=content,
            calendar_type=A_SHARE_INTRADAY_SIGNAL_CALENDAR_TYPE,
        )

    def persist_signal(self, signal: AShareSignalResult, snapshot_time: datetime) -> Optional[int]:
        """Store an intraday signal with minute evaluation enabled."""
        try:
            from finance_analysis.analysis.signal_evaluation import build_initial_evaluation
            from finance_analysis.database.repositories.signal import SignalRepository

            price = float(signal.metrics.get("price") or 0)
            if price <= 0:
                raise ValueError("signal price is missing")
            llm_result = getattr(signal, "llm_result", {}) or {}
            row = SignalRepository().create(
                market="CN",
                code=signal.code,
                name=signal.name,
                signal_type=signal.signal_type,
                signal_version=str(signal.metrics.get("rule_version") or "v1"),
                direction=str(llm_result.get("direction") or "neutral"),
                price=price,
                signal_at=snapshot_time,
                evaluation=build_initial_evaluation(supports_intraday=True),
            )
            return int(row.id)
        except Exception as exc:
            logger.warning("写入 A 股 Signal 失败: %s", exc)
            return None

    def _write_calendar(
        self,
        *,
        time: datetime,
        title: str,
        content: str,
        calendar_type: str,
    ) -> Optional[int]:
        if self._calendar_writer is not None:
            try:
                return self._calendar_writer(
                    time=time, title=title, content=content, calendar_type=calendar_type
                )
            except Exception as exc:
                logger.warning("写入 A 股盘中日历失败(custom): %s", exc)
                return None
        try:
            from finance_analysis.database.repositories.calendar import CalendarRepo
            from finance_analysis.database.repositories.user import UserRepository

            uid = UserRepository().ensure_default_admin()
            entry = CalendarRepo().create(
                uid=uid,
                time=time,
                title=title[:120],
                content=content,
                type=calendar_type,
            )
            return int(getattr(entry, "id", 0) or 0)
        except Exception as exc:
            logger.warning("写入 A 股盘中日历失败: %s", exc)
            return None

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
    ) -> bool:
        if not signals:
            return False
        severity = self._aggregate_severity(signals)
        content = render_aggregated_notification(summary, snapshot, signals)
        if not send_notification:
            return False
        service = self._build_service()
        if service is None:
            return False
        codes = [signal.code for signal in signals]
        state_parts = sorted(
            f"{signal.code}:{signal.signal_type}:{int(signal.metrics.get('state_generation') or 1)}"
            for signal in signals
        )
        state_digest = hashlib.sha256("|".join(state_parts).encode("utf-8")).hexdigest()[:16]
        dedup = f"a_share_intraday_agg:{summary.trading_date.isoformat()}:{state_digest}"
        try:
            return bool(
                service.send(
                    content,
                    email_stock_codes=codes,
                    route_type="alert",
                    severity=severity,
                    dedup_key=dedup,
                    cooldown_key=f"a_share_intraday_agg:{state_digest}",
                )
            )
        except Exception as exc:
            logger.warning("发送 A 股盘中聚合通知失败: %s", exc)
            return False

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

    @staticmethod
    def _summary_title(summary: AShareIntradayTaskSummary) -> str:
        risk_count = sum(
            1
            for s in summary.signal_results
            if s.final_decision == "risk" or s.severity in ("warning", "error")
        )
        regime = _REGIME_LABELS.get(summary.market_regime, summary.market_regime)
        return (
            f"A股盘中分析 {summary.snapshot_time.astimezone(ASIA_SHANGHAI).strftime('%H:%M')}："
            f"{regime}，风险信号 {risk_count} 个"
        )

    @staticmethod
    def _signal_label(signal_type: str) -> str:
        return _SIGNAL_LABELS.get(signal_type, signal_type)


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


def render_summary_content(
    summary: AShareIntradayTaskSummary,
    snapshot: AShareMarketSnapshot,
) -> str:
    stats = snapshot.market_stats or {}
    break_rate = stats.get("break_rate")
    lines = [
        "## A股盘中分析",
        "",
        f"- 时间：{summary.snapshot_time.astimezone(ASIA_SHANGHAI).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 市场阶段：{summary.market_phase}",
        f"- 市场状态：{_REGIME_LABELS.get(summary.market_regime, summary.market_regime)}",
        f"- 上涨/下跌家数：{summary.up_count} / {summary.down_count}",
        f"- 涨停/跌停数量：{summary.limit_up_count} / {summary.limit_down_count}",
        f"- 炸板数量/炸板率：{summary.opened_limit_up_count} / "
        f"{'-' if break_rate is None else f'{break_rate:.2%}'}",
        f"- 两市成交额（亿）：{stats.get('total_amount', '-')}",
        f"- 候选数量：{summary.snapshot_candidate_count}",
        f"- 规则命中数量：{summary.rule_candidate_count}",
        f"- LLM 复核数量：{summary.llm_candidate_count}",
        f"- 通知数量：{summary.notification_count}",
    ]
    if snapshot.indices:
        lines.extend(["", "### 指数表现", ""])
        for code, item in list(snapshot.indices.items())[:8]:
            name = item.get("name", code) if isinstance(item, dict) else code
            chg = item.get("change_pct") if isinstance(item, dict) else None
            lines.append(f"- {name}：{'-' if chg is None else f'{chg:+.2f}%'}")
    if snapshot.sector_leaders:
        lines.append("")
        lines.append("- 领涨板块：" + "、".join(
            f"{s.get('name', '-')}({s.get('change_pct', 0):+.2f}%)" for s in snapshot.sector_leaders[:5]
        ))
    if snapshot.sector_laggers:
        lines.append("- 领跌板块：" + "、".join(
            f"{s.get('name', '-')}({s.get('change_pct', 0):+.2f}%)" for s in snapshot.sector_laggers[:5]
        ))
    if summary.warnings:
        lines.extend(["", "### 数据源警告", "", *[f"- {w}" for w in summary.warnings[:15]]])
    if summary.signal_results:
        lines.extend(["", "### 重要信号", ""])
        for signal in summary.signal_results[:MAX_AGGREGATED_SIGNALS]:
            lines.append(
                f"- {signal.code} {signal.name} {_SIGNAL_LABELS.get(signal.signal_type, signal.signal_type)}"
                f"（{signal.final_decision}）：{str(signal.llm_result.get('summary', '') or '')[:120]}"
            )
    lines.extend(["", "### 市场上下文 JSON", "",
                  f"```json\n{json.dumps(snapshot.to_context_dict(), ensure_ascii=False, indent=2)}\n```"])
    return "\n".join(lines)


def render_signal_content(signal: AShareSignalResult) -> str:
    metrics = signal.metrics
    result = signal.llm_result
    lines = [
        f"## {signal.code} {signal.name} 盘中异动",
        "",
        f"- 信号类型：{_SIGNAL_LABELS.get(signal.signal_type, signal.signal_type)}",
        f"- 板块：{signal.board}",
        f"- 最终决策：{result.get('final_decision', '-')}",
        f"- 方向：{result.get('direction', '-')}",
        f"- 置信度：{result.get('confidence', '-')}",
        f"- 驱动类型：{result.get('driver_type', '-')}",
        f"- 现价：{metrics.get('price', '-')}",
        f"- 涨跌幅：{metrics.get('change_pct', '-')}%",
        f"- 5/15分钟涨跌幅：{metrics.get('change_5m', '-')}% / {metrics.get('change_15m', '-')}%",
        f"- 距涨停：{metrics.get('distance_to_limit_up_pct', '-')}%",
        f"- VWAP：{metrics.get('vwap', '-')}",
        f"- 分时量比：{metrics.get('intraday_volume_ratio', '-')}",
        "",
        "### AI 判断",
        "",
        f"- 摘要：{result.get('summary', '-')}",
        f"- 理由：{result.get('reason', '-')}",
        f"- 风险：{result.get('risk', '-')}",
        f"- 已持仓者：{result.get('holder_suggestion', '-')}",
        f"- 未持仓者：{result.get('observer_suggestion', '-')}",
        f"- T+1 提示：{result.get('t1_warning', '-')}",
        f"- 失效条件：{result.get('invalidation', '-')}",
    ]
    if signal.fallback_used:
        lines.extend(["", "> AI 复核暂不可用，本提示由确定性量价规则生成。"])
    lines.extend(["", "### 指标 JSON", "",
                  f"```json\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n```"])
    return "\n".join(lines)


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
