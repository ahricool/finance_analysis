"""Global, once-per-confirmed-structure alerts for both rolling market feeds."""
import asyncio
from datetime import datetime, timedelta
import json
import logging

from finance_analysis.core.time import utc_now

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


MAX_PER_MINUTE = 3


def minute_key(minute):
    return f"rt:rolling-alert:minute:{minute}"


async def queue_opportunities(redis, symbol, branches, as_of, quote_at, now):
    """Replace this symbol's result within its closed-bar UTC minute."""
    minute = int(as_of.timestamp()) // 60
    if as_of > now or int(now.timestamp()) // 60 != minute:
        return
    key = minute_key(minute)
    try:
        if not branches or not quote_at or not timedelta(0) <= now - quote_at <= timedelta(seconds=60):
            await redis.hdel(key, symbol)
            return
        pipe = redis.pipeline(transaction=True)
        pipe.hset(key, symbol, json.dumps(branches, allow_nan=False))
        pipe.expire(key, 180)
        await pipe.execute()
    except Exception:
        logger.exception("短线机会候选入队失败: %s", symbol)


def delivery_key(symbol, branch):
    identity = branch["structure_id"]
    if branch["kind"] in BREAKOUT_KINDS:
        identity = f"breakout:{branch['direction']}:{branch['started_at']}"
    key = f"rt:rolling-alert:{symbol}:{identity}"
    return f"{key}:extended" if branch.get("status") == "extended" else key


async def select_winners(redis, key, now):
    rows = await redis.hgetall(key)
    ranked = [(symbol, branch) for symbol, raw in rows.items() for branch in json.loads(raw)
              if now < datetime.fromisoformat(branch["expires_at"])]
    ranked.sort(key=lambda item: (-item[1].get("breakout_alert_score", item[1]["quality_score"]),
                                  item[0], item[1]["structure_id"]))
    winners = []
    selected = set()
    for symbol, branch in ranked:
        claim = delivery_key(symbol, branch)
        if claim in selected or await redis.get(claim):
            continue
        if branch["kind"] in BREAKOUT_KINDS and branch["status"] != "extended" and await redis.get(f"{claim}:extended"):
            continue
        selected.add(claim)
        winners.append((symbol, branch))
        if len(winners) == MAX_PER_MINUTE:
            break
    return winners


async def dispatch_minute(redis, now):
    """Freeze at most three winners before any delivery, including across leader restarts."""
    minute = int(now.timestamp()) // 60
    key = minute_key(minute - 1)
    deadline = (minute - 1) * 60 + 90
    if now.timestamp() >= deadline or await redis.get(f"{key}:done"):
        return
    if not await redis.set(f"{key}:sending", "1", ex=5, nx=True):
        return
    selection = f"{key}:winners"
    frozen = await redis.get(selection)
    if frozen is None:
        winners = await select_winners(redis, key, now)
        if not await redis.set(selection, json.dumps(winners), ex=180, nx=True):
            winners = json.loads(await redis.get(selection))
    else:
        winners = json.loads(frozen)
    for symbol, branch in winners:
        at = utc_now()
        if at.timestamp() >= deadline:
            return
        if at < datetime.fromisoformat(branch["expires_at"]) and not await send_opportunity(redis, symbol, branch):
            return
    await redis.set(f"{key}:done", "1", ex=180)


async def dispatch_loop(redis):
    while True:
        try:
            await dispatch_minute(redis, utc_now())
        except Exception:
            logger.exception("短线机会分钟汇总失败")
        await asyncio.sleep(1)


async def send_opportunity(redis, symbol, primary):
    breakout = primary["kind"] in BREAKOUT_KINDS
    if breakout and primary.get("breakout_alert_score", 0) < ALERT_THRESHOLD:
        return True
    key = delivery_key(symbol, primary)
    extended = primary.get("status") == "extended"
    try:
        if breakout and not extended and await redis.get(f"{key}:extended"):
            return True
        if not await redis.set(key, "claimed", ex=86400, nx=True):
            return await redis.get(key) == "sent"
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
            service = get_notification_service()
            persisted = service.send(content, title=title, route_type="alert", severity="info", push=False)
            if persisted.notification_id is not None:
                service.push_existing(content, notification_id=persisted.notification_id, title=title,
                                      route_type="alert", severity="info", dedup_key=key, cooldown_key=key)
            return persisted

        persisted = await asyncio.to_thread(deliver)
        if persisted.notification_id is None:
            await redis.delete(key)
            return False
        await redis.set(key, "sent", ex=86400)
        return True
    except Exception:
        # A transport exception can follow persistence. Keep any existing claim.
        logger.exception("短线机会提醒失败: %s", symbol)
        return False
