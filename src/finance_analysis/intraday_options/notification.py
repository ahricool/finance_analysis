"""Render and dispatch global notifications for simulated intraday trade entries and exits."""

from __future__ import annotations

from datetime import datetime
import logging
import math
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from finance_analysis.config import env_bool, load_env

logger = logging.getLogger(__name__)

TRADE_EVENT_KINDS = frozenset({"entry", "exit"})
_NY_TZ = ZoneInfo("America/New_York")
_CN_TZ = ZoneInfo("Asia/Shanghai")

KIND_LABELS: dict[str, str] = {
    "opening_breakout": "开盘区间突破",
    "midday_wave_breakout": "盘中主浪突破",
    "pivot_breakout": "盘中关键位突破",
    "box_breakout": "箱体突破",
    "box_retest": "突破位回测",
    "trend_continuation": "趋势延续",
    "trend_recovery": "顺势回撤恢复",
}


def trade_notifications_enabled() -> bool:
    """Return whether simulated intraday trade notifications are enabled."""
    load_env()
    return env_bool("INTRADAY_TRADE_NOTIFICATIONS", True)


def is_trade_event(event: Any) -> bool:
    """Return True when *event* is a committed entry or exit trade event."""
    return isinstance(event, Mapping) and event.get("kind") in TRADE_EVENT_KINDS and isinstance(event.get("trade"), Mapping)


def _clean_text(value: str) -> str:
    """Normalize ASCII brackets/underscores so Telegram legacy Markdown renders cleanly."""
    return value.replace("(", "（").replace(")", "）").replace("[", "【").replace("]", "】").replace("_", " ")


def _fmt_price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(price):
        return "—"
    return f"{price:.4f}" if 0 < abs(price) < 1 else f"{price:.2f}"


def _fmt_signed_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(pct):
        return "—"
    return f"{pct:+.2f}%"


def _fmt_dual_clock(value: Any, *, include_seconds: bool = True) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            return str(value)
        if parsed.tzinfo is None:
            return parsed.strftime("%H:%M:%S" if include_seconds else "%H:%M")
        fmt = "%H:%M:%S" if include_seconds else "%H:%M"
        ny = parsed.astimezone(_NY_TZ).strftime(fmt)
        cn = parsed.astimezone(_CN_TZ).strftime(fmt)
        return f"{ny} 美东 / {cn} 北京"
    except (TypeError, ValueError):
        return str(value)


def _fmt_duration(seconds: Any) -> str:
    if seconds is None:
        return "—"
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "—"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分{secs}秒" if secs else f"{hours}小时{minutes}分"
    if minutes > 0:
        return f"{minutes}分{secs}秒" if secs else f"{minutes}分钟"
    return f"{secs}秒"


def _symbol_header(symbol: str, symbol_name: str | None) -> str:
    cleaned = _clean_text(symbol_name.strip()) if symbol_name and symbol_name.strip() else ""
    if cleaned and cleaned.upper() != symbol.upper():
        return f"{symbol}（{cleaned}）"
    return symbol


def _kind_label(kind: Any) -> str:
    raw = str(kind or "").strip()
    if not raw:
        return "日内模拟"
    return KIND_LABELS.get(raw, _clean_text(raw))


def render_trade_notification(
    event: Mapping[str, Any],
    *,
    symbol_name: str | None = None,
) -> tuple[str, str]:
    """Render ``(title, markdown_content)`` for an intraday simulation ``entry`` or ``exit`` event."""
    kind = event.get("kind")
    if kind not in TRADE_EVENT_KINDS:
        raise ValueError(f"Unsupported trade notification event kind: {kind!r}")
    trade = event.get("trade")
    if not isinstance(trade, Mapping):
        raise ValueError("Trade notification event requires a trade payload")

    symbol = str(trade.get("symbol") or event.get("symbol") or "").strip()
    side = int(trade.get("side") or 1)
    direction = "做多" if side == 1 else "做空"
    strategy_label = _kind_label(trade.get("kind"))
    header_symbol = _symbol_header(symbol, symbol_name)
    trading_date = str(trade.get("trading_date") or "—")

    if kind == "entry":
        entry_price = trade.get("entry_price")
        invalidation = trade.get("invalidation")
        target = trade.get("target")
        emoji = "📈" if side == 1 else "📉"
        title = f"日内模拟开仓 · {direction} {symbol} @ {_fmt_price(entry_price)}"
        lines = [
            f"{emoji} **日内模拟开仓 · {direction} {header_symbol}**",
            "",
            f"- 策略路线：{strategy_label}",
            f"- 进场价格：{_fmt_price(entry_price)}",
        ]
        if invalidation is not None and entry_price:
            stop_pct = side * (float(invalidation) - float(entry_price)) / float(entry_price) * 100.0
            lines.append(f"- 止损保护：{_fmt_price(invalidation)}（{_fmt_signed_pct(stop_pct)}）")
        elif invalidation is not None:
            lines.append(f"- 止损保护：{_fmt_price(invalidation)}")

        evidence = trade.get("entry_evidence") if isinstance(trade.get("entry_evidence"), Mapping) else {}
        raw_target_source = str(evidence.get("target_source") or "").strip()
        if raw_target_source.startswith("V7波段止盈(") and raw_target_source.endswith(")"):
            target_source = "V7波段止盈"
        else:
            target_source = _clean_text(raw_target_source)
        if target is not None and entry_price:
            tp_pct = side * (float(target) - float(entry_price)) / float(entry_price) * 100.0
            suffix = f" · {target_source}" if target_source else ""
            lines.append(f"- 目标止盈：{_fmt_price(target)}（{_fmt_signed_pct(tp_pct)}{suffix}）")
        elif target is not None:
            lines.append(f"- 目标止盈：{_fmt_price(target)}")
        else:
            lines.append(f"- 目标止盈：{target_source or '移动止损跟踪'}")

        if trade.get("exit_policy") == "v7_fixed_wave":
            trigger_pct = float(trade.get("profit_lock_trigger_pct") or 0.0)
            lock_pct = float(trade.get("profit_lock_level_pct") or 0.0)
            if trigger_pct > 0:
                lock_label = "成本价保本" if lock_pct == 0 else f"+{lock_pct * 100:.2f}%锁盈"
                lines.append(f"- 锁盈规则：浮盈达 +{trigger_pct * 100:.1f}% 时保护位上移至{lock_label}")

        if trade.get("cutoff"):
            lines.append(f"- 最晚清仓：{_fmt_dual_clock(trade.get('cutoff'), include_seconds=False)}")
        lines.append(f"- 报价时间：{_fmt_dual_clock(trade.get('entry_price_at') or event.get('data_time'))}")
        lines.append(f"- 交易日：{trading_date}")
        return title[:300], "\n".join(lines)

    entry_price = trade.get("entry_price")
    exit_price = trade.get("exit_price")
    return_pct = trade.get("return_pct")
    estimated = bool(trade.get("estimated"))
    exit_reason = _clean_text(str(trade.get("exit_reason") or event.get("reason") or "模拟平仓"))
    if estimated:
        emoji = "⚠️"
    elif return_pct is not None and float(return_pct) > 0:
        emoji = "✅"
    elif return_pct is not None and float(return_pct) < 0:
        emoji = "❌"
    else:
        emoji = "➖"
    title_prefix = "日内模拟平仓（估算）" if estimated else "日内模拟平仓"
    title = f"{title_prefix} · {direction} {symbol} {_fmt_signed_pct(return_pct)}"
    lines = [
        f"{emoji} **{title_prefix} · {direction} {header_symbol}**",
        "",
        f"- 策略路线：{strategy_label}",
        f"- 进场 → 平仓：{_fmt_price(entry_price)} → {_fmt_price(exit_price)}（**{_fmt_signed_pct(return_pct)}**）",
        f"- 平仓原因：{exit_reason}",
        f"- 持仓时长：{_fmt_duration(trade.get('duration_seconds'))}",
        f"- 报价时间：{_fmt_dual_clock(trade.get('exit_price_at') or event.get('data_time'))}",
    ]
    if estimated:
        anomaly = _clean_text(str(trade.get("anomaly") or "截止行情缺失或重启后补记"))
        lines.append(f"- 估算标注：{anomaly}")
        if trade.get("planned_exit_at"):
            lines.append(f"- 计划清仓：{_fmt_dual_clock(trade.get('planned_exit_at'))}")
    lines.append(f"- 交易日：{trading_date}")
    return title[:300], "\n".join(lines)


def _load_symbol_names(symbols: Iterable[str]) -> dict[str, str]:
    codes = sorted({str(symbol).strip() for symbol in symbols if str(symbol or "").strip()})
    if not codes:
        return {}
    try:
        from finance_analysis.database.repositories.stock import InstrumentRepository

        return InstrumentRepository().names_by_codes(codes)
    except Exception:
        logger.debug("加载日内模拟标的中文名称失败，降级使用代码", exc_info=True)
        return {}


def _default_notifier():
    from finance_analysis.notification.service import NotificationService  # pragma: allowlist secret

    return NotificationService()


def notify_trade_events(
    events: Sequence[Mapping[str, Any]],
    *,
    notifier_factory: Callable[[], Any] | None = None,
    names_loader: Callable[[Iterable[str]], Mapping[str, str]] | None = None,
) -> int:
    """Persist and push Telegram/ntfy notifications for committed entry/exit events (fail-open)."""
    trade_events = [event for event in events if is_trade_event(event)]
    if not trade_events or not trade_notifications_enabled():
        return 0

    symbols = [str(event["trade"].get("symbol") or event.get("symbol") or "").strip() for event in trade_events]
    try:
        symbol_names = dict((names_loader or _load_symbol_names)(symbols) or {})
    except Exception:
        logger.debug("日内模拟交易通知获取名称异常，降级使用代码", exc_info=True)
        symbol_names = {}

    factory = notifier_factory or _default_notifier
    sent_count = 0
    for event in trade_events:
        trade = event["trade"]
        symbol = str(trade.get("symbol") or event.get("symbol") or "").strip()
        kind = str(event["kind"])
        trade_id = str(event.get("trade_id") or trade.get("id") or f"{symbol}:{event.get('at') or ''}")
        dedup_key = f"intraday-simulation:{kind}:{trade_id}"
        severity = "warning" if kind == "exit" and bool(trade.get("estimated")) else "info"
        try:
            title, content = render_trade_notification(event, symbol_name=symbol_names.get(symbol))
            result = factory().send(
                content,
                route_type="alert",
                severity=severity,
                dedup_key=dedup_key,
                cooldown_key=dedup_key,
                uid=None,
                title=title,
            )
            if getattr(result, "notification_id", None) is not None or getattr(result, "push_sent", False):
                sent_count += 1
        except Exception:
            logger.exception("日内模拟交易通知失败: kind=%s symbol=%s trade_id=%s", kind, symbol, trade_id)
    return sent_count
