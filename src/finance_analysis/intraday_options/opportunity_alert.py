"""Global, once-per-confirmed-structure alerts for both rolling market feeds."""
import asyncio
from datetime import datetime, timedelta
import logging

from finance_analysis.intraday_options.breakout_alerts import ALERT_THRESHOLD, BREAKOUT_KINDS
from finance_analysis.intraday_options.notification import KIND_LABELS
from finance_analysis.notification.service import get_notification_service

logger = logging.getLogger(__name__)


def breakout_priority(branch):
    return (branch["breakout_alert_score"], branch["status"] == "extended", branch["kind"] == "pivot_breakout",
            branch["structure_id"])


def alert_candidates(opportunities):
    if not opportunities or opportunities.get("reference", True):
        return []
    as_of = opportunities["as_of"]
    primary = opportunities.get("primary")
    candidates = []
    breakouts = {}
    for branch in opportunities["branches"]:
        if branch.get("superseded_by") or branch.get("breakout_rejection"):
            continue
        if branch["kind"] in BREAKOUT_KINDS:
            if branch.get("breakout_alert_score", 0) < ALERT_THRESHOLD:
                continue
            qualified = branch["breakout_alert_at"]
            extended = branch.get("extended_at")
            if branch["status"] == "extended":
                eligible = extended and max(qualified, extended) == as_of
            else:
                eligible = branch["status"] == "confirmed" and not extended and qualified == as_of
            if eligible:
                direction = branch["direction"]
                previous = breakouts.get(direction)
                if previous is None or breakout_priority(branch) > breakout_priority(previous):
                    breakouts[direction] = branch
        elif branch["status"] == "extended" and branch.get("extended_at") == as_of:
            candidates.append(branch)
        elif branch["status"] == "confirmed" and primary and branch["structure_id"] == primary["structure_id"]:
            candidates.append(branch)
    return [*candidates, *breakouts.values()]


async def alert_opportunity(redis, symbol, primary, as_of, quote_at, now):
    if not primary or not quote_at:
        return
    if not (timedelta(0) <= now - quote_at <= timedelta(seconds=60)
            and timedelta(0) <= now - as_of < timedelta(seconds=90)
            and now < datetime.fromisoformat(primary["expires_at"])):
        return
    breakout = primary["kind"] in BREAKOUT_KINDS
    if breakout and primary.get("breakout_alert_score", 0) < ALERT_THRESHOLD:
        return
    identity = primary["structure_id"]
    if breakout:
        identity = f"breakout:{primary['direction']}:{primary['started_at']}"
    key = f"rt:rolling-alert:{symbol}:{identity}"
    extended = primary.get("status") == "extended"
    if extended:
        key += ":extended"
    try:
        if breakout and not extended and await redis.get(f"{key}:extended"):
            return
        if not await redis.set(key, "claimed", ex=86400, nx=True):
            return
        kind = KIND_LABELS[primary["kind"]]
        direction = "偏多" if primary["direction"] == "bullish" else "偏空"
        title = f"{symbol} 短线机会 · {kind} · {direction}"
        reason = "已延伸" if extended else primary.get("breakout_alert_reason")
        if reason:
            title += f" · {reason}"
        confirmed = datetime.fromisoformat(primary["confirmed_at"])
        expires = datetime.fromisoformat(primary["expires_at"])
        strength = f"突破证据 {primary['breakout_alert_score']:.1f}/100 分，" if breakout else ""
        content = (f"{title}\n{strength}形态质量 {primary['quality_score']:.0f} 分，触发位 {primary['trigger']:.8g}，"
                   f"失效位 {primary['invalidation']:.8g}。\n确认于 {confirmed:%Y-%m-%d %H:%M %Z}，"
                   f"有效至 {expires:%H:%M %Z}。")

        evidence = primary.get("breakout_alert_context")
        if evidence:
            content += (f"\n首次达标时收盘越过小时边界 {evidence['hour_edge']:.8g} 达 {evidence['distance_atr']:.2f} ATR，"
                        f"突破段均量为此前一小时均量的 {evidence['volume_ratio']:.1f} 倍。")
        if extended:
            content += "\n价格已远离触发位，提示跟踪原形态进展。"

        def deliver():
            return get_notification_service().send(content, title=title, route_type="alert", severity="info",
                                                   dedup_key=key, cooldown_key=key)

        try:
            persisted = await asyncio.to_thread(deliver)
            if persisted.notification_id is None:
                await redis.delete(key)
        except Exception:
            await redis.delete(key)
            raise
    except Exception:
        logger.exception("短线机会提醒失败: %s", symbol)
