"""Causal, latest-only entry setups. Trend quality is deliberately not added to entry quality."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from finance_analysis.intraday_options.structure import atr, box, metrics
from finance_analysis.intraday_options.analysis_window import HORIZON, REQUIRED_MINUTES, analysis_window, observed
from finance_analysis.intraday_options.rules import CONTINUATION, ENTRY_VERSION, RULES, entry_interval
from finance_analysis.intraday_options.continuation import setup, confirmation, pullback_anchor
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds

MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class OpportunityConfig:
    background: int = 30
    minimum_background: int = REQUIRED_MINUTES
    touch_atr: float = 0.3
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
    rule = RULES[kind]
    return {
        "kind": kind,
        "direction": "bullish" if side == 1 else "bearish",
        "status": "forming",
        "structure_id": f"{kind}:{side}:{when.isoformat()}",
        "trigger": trigger,
        "invalidation": trigger - side * rule.failure_atr * scale,
        "atr": scale,
        "formation_start": start.isoformat(),
        "started_at": when.isoformat(),
        "confirmed_at": None,
        "expires_at": (when + rule.lifetime * MINUTE).isoformat(),
        "rule_version": ENTRY_VERSION,
        "confirmation_method": None,
        "atr_source": "legacy_including_flat_bars",
        "quality_score": None,
        "distance_atr": None,
        "risk_atr": None,
        "components": {"structure": structure_quality},
        "reasons": [],
    }


def advance(branch, history):
    """Advance frozen shape evidence; expired/invalidated processes cannot revive."""
    if branch.get("superseded_by"):
        return
    bar = history[-1]
    side = 1 if branch["direction"] == "bullish" else -1
    scale, level = branch["atr"], branch["trigger"]
    rule = RULES[branch["kind"]]
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
    if branch["status"] in {"invalidated", "expired"}:
        return
    when = (bar.bar_time + MINUTE).isoformat()
    if when >= branch["expires_at"]:
        branch.update(status="expired", reasons=[f"本次机会已超过{rule.lifetime}分钟观察期，等待独立的新触发"])
        return
    extreme = float(bar.low if side > 0 else bar.high)
    if (branch["kind"] != "box_breakout" or when > branch["started_at"]) and (
        extreme - branch["invalidation"]
    ) * side < 0:
        branch.update(status="invalidated", reasons=["触及固定失效位，原机会不再恢复"])
        return
    threshold = rule.confirm_atr
    pair = history[-2:]
    restored = (
        len(pair) == 2
        and continuous(pair, 2)
        and all(observed(b) for b in pair)
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
    method, wait_reason = "two_closes", "等待触及后的相邻两根闭合K恢复确认"
    if branch["kind"] == "trend_continuation":
        restored, method, wait_reason = confirmation(branch, history)
        if branch["status"] == "expired":
            branch["reasons"] = [wait_reason]
            return
    if restored and branch["confirmed_at"] is None:
        branch["confirmed_at"] = when
        branch["confirmation_method"] = method
    if branch["confirmed_at"] and distance > rule.extended_atr:
        branch.update(status="extended", reasons=[f"形态已确认但距离固定触发位超过{rule.extended_atr:g} ATR"])
    elif branch["confirmed_at"] and restored:
        branch.update(status="confirmed", reasons=["强突破真实闭合K确认" if method == "strong_break"
                                                  else "相邻两根真实闭合K确认，当前未延伸"])
    else:
        branch.update(status="forming", reasons=[wait_reason])
    if branch["kind"] == "trend_recovery":
        branch["reasons"].append("恢复还需最近5分钟顺向移动至少0.2 ATR、路径效率至少35%")


def detect(bars):
    """Replay bounded input in chronological order; no future pivot or rolling event level."""
    branches = {}
    archive = []
    diagnostics = {}
    opening, _ = session_bounds("US", market_trading_date(bars[-1].bar_time, "US"))
    window_start = max(opening, bars[-1].bar_time - (HORIZON - 1) * MINUTE)
    for index, bar in enumerate(bars):
        history = bars[: index + 1]
        prior = bars[max(0, index - CONFIG.background) : index]
        # Use up to 30 contiguous background minutes; opening needs only 15.
        for j in range(len(prior) - 1, 0, -1):
            if prior[j].bar_time - prior[j - 1].bar_time != MINUTE:
                prior = prior[j:]
                break
        for branch in [*archive, *branches.values()]:
            advance(branch, history)
        # Do not rediscover old structures with a truncated background when the
        # 60m replay moves forward. Live lifetimes fit inside the full context.
        if window_start > opening and bar.bar_time < window_start + CONFIG.background * MINUTE:
            continue
        for side in (1, -1):
            details, reason = setup(history, side)
            if details and window_start > opening and datetime.fromisoformat(details["structure_start"]) < (
                window_start + CONTINUATION.background * MINUTE
            ):
                details = None
            diagnostics[side] = reason
            key = ("trend_continuation", side)
            existing = branches.get(key)
            if details and (existing is None or (
                details["structure_start"] > existing["structure_end"]
                and details["structure_start"] > (existing.get("triggered_at") or existing["started_at"])
            )):
                branch = new_branch("trend_continuation", side, details["trigger"], details["atr"], bar,
                                    datetime.fromisoformat(details["structure_start"]), details.pop("structure_quality"))
                branch.update(details, triggered_at=None)
                branch["structure_id"] = f"trend_continuation:{side}:{details['structure_start']}"
                if existing:
                    existing["superseded_by"] = branch["structure_id"]
                    archive.append(existing)
                branches[key] = branch
                advance(branch, history)
        if (not observed(bar) or not continuous(prior, CONFIG.minimum_background)
                or bar.bar_time - prior[-1].bar_time != MINUTE):
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
                if (float(bar.close) - level) * side > RULES["box_breakout"].confirm_atr * bounds["atr"]:
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
                if -RULES["box_retest"].failure_atr <= depth <= CONFIG.touch_atr:
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
            anchor = pullback_anchor(history, side,
                                     since=existing["started_at"] if existing else None,
                                     scale=existing["atr"] if existing else scale)
            if existing and not anchor:
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
                anchor = anchor or bar.bar_time.isoformat()
                branch.update(structure_start=anchor, structure_end=(bar.bar_time + MINUTE).isoformat(),
                              structure_high=max(float(b.high) for b in history if b.bar_time.isoformat() >= anchor),
                              structure_low=min(float(b.low) for b in history if b.bar_time.isoformat() >= anchor),
                              process_id=f"trend:{side}:{anchor}")
                if existing:
                    existing["superseded_by"] = branch["structure_id"]
                    archive.append(existing)
                branches[key] = branch
                advance(branch, history)
    diagnostics = [reason for side, reason in diagnostics.items() if reason and not any(
        b["kind"] == "trend_continuation" and b["direction"] == ("bullish" if side > 0 else "bearish")
        and b["status"] not in {"expired", "invalidated"} for b in branches.values()
    )]
    return [*archive, *branches.values()], list(dict.fromkeys(diagnostics))


def calculate_opportunities(ordered):
    end = ordered[-1].bar_time
    bars, coverage, reasons = analysis_window(ordered)
    branches, diagnostics = detect(bars) if bars else ([], [])
    for branch in branches:
        branch["entry_low"], branch["entry_high"] = entry_interval(branch)
        branch["max_risk_atr"] = RULES[branch["kind"]].max_risk_atr
    reference = coverage["reference"]
    valid = [b for b in branches if b["status"] == "confirmed" and not b.get("superseded_by")
             and not b.get("breakout_rejection")] if not reference else []
    primary = min(valid, key=lambda b: (-b["quality_score"], b["kind"], b["structure_id"])) if valid else None
    priority = {"confirmed": 0, "forming": 1, "extended": 2, "invalidated": 3, "expired": 4}
    branches.sort(key=lambda b: (bool(b.get("superseded_by")), priority[b["status"]],
                                -b["quality_score"], b["kind"], b["structure_id"]))
    return {
        "version": ENTRY_VERSION,
        "primary": primary,
        "branches": branches,
        **coverage,
        "as_of": (end + MINUTE).isoformat(),
        "reasons": reasons + diagnostics + ([] if primary else ["当前没有数据完整、已确认且未延伸的入场分支"]),
    }
