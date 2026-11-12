"""Deterministic, symmetric log-price metrics using closed regular-session bars only."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Sequence

import numpy as np

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.intraday_options.config import COMPOSITE_WINDOWS, CONFIG, VERSION, WINDOW_WEIGHTS, WINDOWS
from finance_analysis.market_stream.config import is_regular_trade_session, market_trading_date
from finance_analysis.market_stream.session import session_bounds

MINUTE = timedelta(minutes=1)


def unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def log_ranges(bars: Sequence[CandleState]) -> np.ndarray:
    previous = [float(bars[0].open), *[float(b.close) for b in bars[:-1]]]
    return np.array(
        [
            max(
                math.log(float(b.high) / float(b.low)),
                abs(math.log(float(b.high) / p)),
                abs(math.log(float(b.low) / p)),
            )
            for b, p in zip(bars, previous)
        ]
    )


def window_score(bars: Sequence[CandleState], minutes: int) -> dict:
    """Use observed prices at actual minute offsets; never synthesize missing candles."""
    y = np.log([float(bars[0].open), *[float(b.close) for b in bars]])
    x = np.array([0.0, *[(b.bar_time - bars[0].bar_time).total_seconds() / 60 + 1 for b in bars]])
    centered = y - y.mean()
    slope = float(np.dot(x - x.mean(), centered) / np.sum((x - x.mean()) ** 2))
    fitted = y.mean() + slope * (x - x.mean())
    variance = float(np.sum(centered**2))
    stability = unit(1 - float(np.sum((y - fitted) ** 2)) / variance) if variance > 1e-18 else 0.0
    moves = np.diff(y)
    net = float(y[-1] - y[0])
    travel = float(np.sum(np.abs(moves)))
    efficiency = unit(abs(net) / travel) if travel > 1e-12 else 0.0
    atr = float(log_ranges(bars).mean())
    scale = atr * math.sqrt(minutes)
    strength = abs(net) / scale if scale > 1e-12 else 0.0
    sign = 1 if net > 0 else -1 if net < 0 else 0
    direction = (
        sign
        if (
            abs(net) >= CONFIG.neutral_move
            and strength >= CONFIG.neutral_strength
            and efficiency >= CONFIG.neutral_efficiency
            and slope * sign > 0
        )
        else 0
    )
    # Reflect a downtrend into an uptrend before measuring adverse excursions.
    oriented = (y - y[0]) * sign
    drawdowns = np.maximum.accumulate(oriented) - oriented
    adverse = float(drawdowns.max()) / scale if scale > 1e-12 else 0.0
    longest = run = 0
    for distance, elapsed in zip(drawdowns[1:], np.diff(x)):
        run = run + elapsed if distance > 1e-10 else 0
        longest = max(longest, run)
    duration = longest / minutes
    disturbance = 0.7 * (1 - unit(adverse)) + 0.3 * (1 - unit(duration))
    gate = min(unit(abs(net) / CONFIG.full_move), unit(strength / CONFIG.full_gate_strength))
    parts = {
        "stability": stability * 100,
        "efficiency": efficiency * 100,
        "strength": unit(strength / CONFIG.full_strength) * 100,
        "disturbance": disturbance * 100,
    }
    raw = sum(
        parts[k] * w
        for k, w in (
            ("stability", CONFIG.stability_weight),
            ("efficiency", CONFIG.efficiency_weight),
            ("strength", CONFIG.strength_weight),
            ("disturbance", CONFIG.disturbance_weight),
        )
    )
    quality = raw * gate
    concentration = float(np.max(np.abs(moves))) / travel if travel > 1e-12 else 0.0
    recent_minutes = min(5, max(2, minutes // 3))
    recent_index = int(np.searchsorted(x, x[-1] - recent_minutes, side="left"))
    recent = float(y[-1] - y[recent_index]) * sign
    stalled_impulse = (
        concentration >= CONFIG.impulse_concentration and recent < abs(net) * CONFIG.recent_extension_fraction
    )
    reasons = []
    if gate < 1:
        reasons.append("移动幅度不足，应用移动门槛折扣")
    if stalled_impulse:
        quality = min(quality, CONFIG.impulse_cap)
        direction = 0
        reasons.append(f"移动集中于单根分钟线，最近{recent_minutes}分钟延续不足，方向暂按中性")
    if direction == 0:
        quality = min(quality, 35.0)
        if not stalled_impulse:
            reasons.append("斜率、幅度或路径效率处于中性区间")
    return {
        "minutes": minutes,
        "data_status": "ready",
        "direction": direction,
        "score": round(quality, 2),
        "return_pct": math.expm1(net) * 100,
        "start_at": bars[0].bar_time.isoformat(),
        "end_at": (bars[-1].bar_time + MINUTE).isoformat(),
        "stability": parts["stability"],
        "efficiency": parts["efficiency"],
        "strength": parts["strength"],
        "disturbance": parts["disturbance"],
        "normalized_move": strength,
        "adverse_move": adverse,
        "adverse_duration": duration,
        "movement_gate": gate,
        "concentration": concentration,
        "stalled_impulse": stalled_impulse,
        "reasons": reasons,
    }


def combine(windows: list[dict], bars: Sequence[CandleState]) -> dict:
    by_minutes = {w["minutes"]: w for w in windows}
    windows = [by_minutes.get(n, {"minutes": n, "score": None}) for n in COMPOSITE_WINDOWS]
    if any(w.get("score") is None for w in windows):
        return {
            "score": None,
            "direction": None,
            "state": None,
            "base_score": None,
            "alignment": None,
            "extension_atr": None,
            "explanation": "等待15、30、60分钟窗口预热及至少2根有效分钟线。",
        }
    directions = [w["direction"] for w in windows]
    short, main, long = directions
    base = sum(w["score"] * weight for w, weight in zip(windows, WINDOW_WEIGHTS))
    alignment = abs(sum(d * weight for d, weight in zip(directions, WINDOW_WEIGHTS)))
    score = base * (0.4 + 0.6 * alignment)
    if main != 0 and main == long:
        direction = "bullish" if main > 0 else "bearish"
    elif main != 0 and short == main and long == 0:
        direction = "bullish" if main > 0 else "bearish"
    elif 1 in directions and -1 in directions:
        direction = "conflict"
    else:
        direction = "neutral"
    recent = [b for b in bars if b.bar_time >= bars[-1].bar_time - MINUTE * 19]
    logs = np.log([float(b.close) for b in recent])
    ema = float(logs[0])
    for value in logs[1:]:
        ema += 2 / 21 * (float(value) - ema)
    atr = float(log_ranges(recent).mean())
    extension = abs(float(logs[-1]) - ema) / atr if atr > 1e-12 else 0.0
    sign = 1 if direction == "bullish" else -1
    if direction == "conflict":
        state, score = "conflict", min(score, 55.0)
        explanation = "短周期与长周期方向冲突，可能发生转折，等待方向重新一致。"
    elif direction == "neutral":
        state, score = "waiting", min(score, 35.0)
        explanation = "多个窗口缺乏有效方向，当前更接近震荡，等待方向。"
    elif short != main:
        state, score = "pullback", min(score, 65.0)
        explanation = "30/60分钟主趋势仍在，最近15分钟转弱或反向，处于回撤观察。"
    elif extension >= CONFIG.extension_atr and float(logs[-1] - logs[max(0, len(logs) - 6)]) * sign > 0:
        state = "extended"
        explanation = "方向仍有延续，但偏离短期趋势参考线较远，标记短线延伸；高分不代表适合追入。"
    else:
        state = "continuing"
        explanation = "多个窗口方向一致，近期仍在延续。"
    if any(w["stalled_impulse"] for w in windows):
        explanation += " 部分窗口移动集中于单根急涨/急跌，后续延续不足，已限制窗口分数。"
    return {
        "score": round(score, 2),
        "direction": direction,
        "state": state,
        "base_score": round(base, 2),
        "alignment": alignment,
        "extension_atr": extension,
        "explanation": explanation,
    }


def closed_session_bars(symbol: str, bars: Sequence[CandleState], now: datetime) -> list[CandleState]:
    """Select actual regular-session minutes, including early closes; retain bad bars as gaps."""
    by_time = {}
    for bar in bars:
        if (
            bar.symbol != symbol
            or not bar.confirmed
            or bar.bar_time + MINUTE > now
            or not is_regular_trade_session(bar.trade_session)
        ):
            continue
        bounds = session_bounds("US", market_trading_date(bar.bar_time, "US"))
        if bounds and bounds[0] <= bar.bar_time < bounds[1]:
            existing = by_time.get(bar.bar_time)
            if existing is None or bar.received_at >= existing.received_at:
                by_time[bar.bar_time] = bar
    if not by_time:
        return []
    day = market_trading_date(max(by_time), "US")
    return [by_time[t] for t in sorted(by_time) if market_trading_date(t, "US") == day]


def calculate(symbol: str, bars: Sequence[CandleState], now: datetime) -> dict | None:
    """Only latest observed session is evaluated; never backfill historical decisions on warmup."""
    ordered = closed_session_bars(symbol, bars, now)
    if not ordered:
        return None
    by_time = {b.bar_time: b for b in ordered}
    latest = ordered[-1].bar_time
    day = market_trading_date(latest, "US")
    start, _ = session_bounds("US", day)
    windows = []
    for minutes in WINDOWS:
        times = [latest - MINUTE * i for i in reversed(range(minutes))]
        if times[0] < start:
            windows.append({"minutes": minutes, "data_status": "warming", "score": None})
        else:
            usable = [by_time[t] for t in times if t in by_time and by_time[t].is_valid()
                      and not by_time[t].partial and not by_time[t].sampled]
            missing = minutes - len(usable)
            quality = {"available_bars": len(usable), "missing_bars": missing}
            if len(usable) < 2:
                windows.append({"minutes": minutes, "data_status": "gap", "score": None, **quality,
                                "reasons": ["有效分钟线少于2根，无法计算趋势"]})
                continue
            window = window_score(usable, minutes)
            window.update(quality)
            if missing:
                window["data_status"] = "gap"
                window["reasons"].append(f"窗口缺少{missing}根有效分钟线，按现有{len(usable)}根计算，仅供参考")
            windows.append(window)
    usable = [b for b in ordered if b.is_valid() and not b.partial and not b.sampled]
    combined = combine(windows, usable)
    if any(w["data_status"] == "gap" for w in windows):
        combined["explanation"] = "分钟数据不完整，按现有K线计算，仅供参考。" + combined["explanation"]
    return {
        "version": VERSION,
        "symbol": symbol,
        "trading_date": day.isoformat(),
        "as_of": (latest + MINUTE).isoformat(),
        "observed_at": now.isoformat(),
        "windows": windows,
        **combined,
    }
