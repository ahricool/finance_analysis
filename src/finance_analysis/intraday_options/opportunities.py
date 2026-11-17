"""Causal, latest-only entry setups. Trend quality is deliberately not added to entry quality."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from finance_analysis.intraday_options.structure import atr, box, metrics
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds

MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class OpportunityConfig:
    horizon: int = 60
    background: int = 30
    lifetime: int = 15
    breakout_atr: float = 0.2
    touch_atr: float = 0.3
    recovery_atr: float = 0.1
    failure_atr: float = 0.75
    extended_atr: float = 2.0
    trend_stability: float = 0.6
    trend_efficiency: float = 0.35
    recent_move_atr: float = 0.2


CONFIG = OpportunityConfig()


def clip(value):
    return max(0.0, min(1.0, value))


def continuous(bars, count):
    return len(bars) >= count and all(b.bar_time - a.bar_time == MINUTE for a, b in zip(bars, bars[1:]))


def new_branch(kind, side, trigger, scale, bar, start, structure_quality):
    when = bar.bar_time + MINUTE
    return {
        "kind": kind,
        "direction": "bullish" if side == 1 else "bearish",
        "status": "forming",
        "structure_id": f"{kind}:{side}:{when.isoformat()}",
        "trigger": trigger,
        "invalidation": trigger - side * CONFIG.failure_atr * scale,
        "atr": scale,
        "formation_start": start.isoformat(),
        "started_at": when.isoformat(),
        "confirmed_at": None,
        "expires_at": (when + CONFIG.lifetime * MINUTE).isoformat(),
        "quality_score": None,
        "distance_atr": None,
        "risk_atr": None,
        "components": {"structure": structure_quality},
        "reasons": [],
    }


def advance(branch, history):
    """Two adjacent closes confirm; an expired/invalidated process cannot revive."""
    bar = history[-1]
    side = 1 if branch["direction"] == "bullish" else -1
    scale, level = branch["atr"], branch["trigger"]
    distance = (float(bar.close) - level) * side / scale
    risk = (float(bar.close) - branch["invalidation"]) * side / scale
    parts = {
        "structure": branch["components"]["structure"],
        "distance": 100 * math.exp(-0.5 * ((distance - 0.5) / 1.0) ** 2),
        "recovery": 100 * clip(distance / 0.5),
        "risk": 100 * (1 - clip(max(0, risk) / 3)),
    }
    quality = 0.25 * parts["structure"] + 0.35 * parts["distance"] + 0.25 * parts["recovery"] + 0.15 * parts["risk"]
    branch.update(distance_atr=distance, risk_atr=risk, components=parts, quality_score=round(quality, 2))
    if branch["status"] == "invalidated":
        return
    when = (bar.bar_time + MINUTE).isoformat()
    if when >= branch["expires_at"]:
        branch.update(status="expired", reasons=["本次机会已超过15分钟观察期，等待独立的新触发"])
        return
    extreme = float(bar.low if side > 0 else bar.high)
    if (branch["kind"] != "box_breakout" or when > branch["started_at"]) and (
        extreme - level
    ) * side < -CONFIG.failure_atr * scale:
        branch.update(status="invalidated", reasons=["触及固定失效位，原机会不再恢复"])
        return
    threshold = CONFIG.breakout_atr if branch["kind"] != "trend_recovery" else CONFIG.recovery_atr
    pair = history[-2:]
    restored = (
        len(pair) == 2
        and continuous(pair, 2)
        and all((float(b.close) - level) * side > threshold * scale for b in pair)
        and (pair[0].bar_time + MINUTE).isoformat() >= branch["started_at"]
    )
    if branch["kind"] == "trend_recovery":
        recent = history[-5:]
        _, _, efficiency = metrics(recent)
        restored = (
            restored
            and continuous(recent, 5)
            and efficiency >= CONFIG.trend_efficiency
            and (float(recent[-1].close) - float(recent[0].close)) * side >= CONFIG.recent_move_atr * scale
        )
    if restored and branch["confirmed_at"] is None:
        branch["confirmed_at"] = when
    if branch["confirmed_at"] and distance > CONFIG.extended_atr:
        branch.update(status="extended", reasons=["已确认但距离固定触发位超过2 ATR，等待新的机会"])
    elif branch["confirmed_at"] and restored:
        branch.update(status="confirmed", reasons=["相邻两根闭合K收在固定触发位外，当前未延伸"])
    else:
        branch.update(status="forming", reasons=["等待触及后的相邻两根闭合K恢复确认"])
    if branch["kind"] == "trend_recovery":
        branch["reasons"].append("恢复还需最近5分钟顺向移动至少0.2 ATR、路径效率至少35%")


def detect(bars):
    """Replay bounded input in chronological order; no future pivot or rolling event level."""
    branches = {}
    for index, bar in enumerate(bars):
        history = bars[: index + 1]
        prior = bars[max(0, index - CONFIG.background) : index]
        for branch in branches.values():
            advance(branch, history)
        if not continuous(prior, CONFIG.background) or bar.bar_time - prior[-1].bar_time != MINUTE:
            continue
        bounds = box(prior, prior[-1].bar_time)
        scale = atr(prior)
        if scale <= 0:
            continue
        slope, stability, efficiency = metrics(prior)
        ema = float(prior[0].close)
        for previous in prior[1:]:
            ema += 2 / 21 * (float(previous.close) - ema)
        for side in (1, -1):
            key = ("box_breakout", side)
            active = branches.get(key)
            # Keep a process for its full lifetime, even after failure; no rolling rediscovery.
            free = active is None or (bar.bar_time + MINUTE).isoformat() >= active["expires_at"]
            if bounds and free:
                level = bounds["upper"] if side > 0 else bounds["lower"]
                if (float(bar.close) - level) * side > CONFIG.breakout_atr * bounds["atr"]:
                    active = new_branch(
                        "box_breakout",
                        side,
                        level,
                        bounds["atr"],
                        bar,
                        prior[0].bar_time,
                        100 * (1 - metrics(prior)[2]),
                    )
                    active["process_id"] = active["structure_id"]
                    active["measurement_target"] = level + side * (bounds["upper"] - bounds["lower"])
                    branches[key] = active
                    advance(active, history)
            retest_key = ("box_retest", side)
            retest = branches.get(retest_key)
            if (
                active
                and active["confirmed_at"]
                and active["status"] not in {"invalidated", "expired"}
                and active["confirmed_at"] < (bar.bar_time + MINUTE).isoformat()
                and (retest is None or retest["started_at"] < active["started_at"])
            ):
                extreme = float(bar.low if side > 0 else bar.high)
                depth = (extreme - active["trigger"]) * side / active["atr"]
                if -CONFIG.failure_atr <= depth <= CONFIG.touch_atr:
                    retest = new_branch(
                        "box_retest",
                        side,
                        active["trigger"],
                        active["atr"],
                        bar,
                        datetime.fromisoformat(active["formation_start"]),
                        active["components"]["structure"],
                    )
                    # A retest cannot outlive its original breakout process.
                    retest["expires_at"] = active["expires_at"]
                    retest["process_id"] = active["structure_id"]
                    retest["measurement_target"] = active.get("measurement_target")
                    branches[retest_key] = retest
                    advance(retest, history)
            key = ("trend_recovery", side)
            existing = branches.get(key)
            if existing and (bar.bar_time + MINUTE).isoformat() < existing["expires_at"]:
                continue
            extreme = float(bar.low if side > 0 else bar.high)
            prior_close = float(prior[-1].close)
            qualified = (
                slope * side > 0
                and stability >= CONFIG.trend_stability
                and efficiency >= CONFIG.trend_efficiency
                and (prior_close - float(prior[0].close)) * side >= scale
                and (prior_close - ema) * side >= 0.5 * scale
            )
            touched = (extreme - ema) * side <= CONFIG.touch_atr * scale and (
                prior_close - extreme
            ) * side >= 0.25 * scale
            if qualified and touched:
                branch = new_branch(
                    "trend_recovery",
                    side,
                    ema,
                    scale,
                    bar,
                    prior[0].bar_time,
                    100 * (0.5 * stability + 0.5 * efficiency),
                )
                branches[key] = branch
                advance(branch, history)
    return list(branches.values())


def calculate_opportunities(ordered):
    end = ordered[-1].bar_time
    opening, _ = session_bounds("US", market_trading_date(end, "US"))
    start = max(opening, end - (CONFIG.horizon - 1) * MINUTE)
    bars = [b for b in ordered if start <= b.bar_time <= end and b.is_valid() and not b.partial and not b.sampled]
    expected = int((end - start) / MINUTE) + 1
    missing = expected - len(bars)
    warming = end - opening < CONFIG.background * MINUTE
    branches = detect(bars) if bars else []
    reference = missing > 0 or warming
    valid = [b for b in branches if b["status"] == "confirmed"] if not reference else []
    primary = min(valid, key=lambda b: (-b["quality_score"], b["kind"], b["structure_id"])) if valid else None
    priority = {"confirmed": 0, "forming": 1, "extended": 2, "invalidated": 3, "expired": 4}
    branches.sort(key=lambda b: (priority[b["status"]], -b["quality_score"], b["kind"], b["structure_id"]))
    return {
        "version": "intraday_entry_v1",
        "primary": primary,
        "branches": branches,
        "reference": reference,
        "missing_bars": missing,
        "as_of": (end + MINUTE).isoformat(),
        "reasons": (["需要30根完整背景K及后续触发确认"] if warming else [])
        + ([f"观察区间缺{missing}根有效K，分支只供参考，不列入有效机会"] if missing else [])
        + ([] if primary else ["当前没有数据完整、已确认且未延伸的入场分支"]),
    }
