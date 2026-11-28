"""Score closed-minute evidence for notifications from a frozen breakout level."""

from datetime import datetime

from finance_analysis.intraday_options.analysis_window import MINUTE, observed
from finance_analysis.intraday_options.structure import atr


BREAKOUT_KINDS = {"pivot_breakout", "midday_wave_breakout", "box_breakout"}
ALERT_THRESHOLD = 95
BACKGROUND = 60


def tested_edge(background, side, edge, scale):
    """Require two tests of the hourly boundary with a distinct retreat between them."""
    first_test = None
    retreated = False
    for i, b in enumerate(background):
        extreme = side * float(b.high if side > 0 else b.low)
        if edge - extreme <= 0.5 * scale:
            if first_test is None:
                first_test = i
            elif retreated and i - first_test >= 5:
                return True
        elif first_test is not None and edge - side * float(b.close) >= scale:
            retreated = True
    return False


def score_breakout(branch, bars, start):
    """Freeze the pre-break range and liquidity. Record the earliest qualifying closed bar."""
    if start < BACKGROUND or branch["status"] not in {"confirmed", "extended"}:
        return
    background = bars[start - BACKGROUND:start]
    leg = bars[start:]
    if leg[-1].bar_time - background[0].bar_time != (BACKGROUND + len(leg) - 1) * MINUTE:
        return
    if not all(b.confirmed and b.is_valid() and observed(b) and not (b.partial or b.sampled)
               for b in (*background, *leg)):
        return
    if sum(b.volume > 0 for b in background) < 45:
        return
    side = 1 if branch["direction"] == "bullish" else -1
    edge = max(side * float(b.high if side > 0 else b.low) for b in background)
    level = side * branch["trigger"]
    scale = max(branch["atr"], atr(background))
    if scale <= 0 or not tested_edge(background, side, edge, scale):
        return
    normal_volume = sum(float(b.volume) for b in background) / BACKGROUND
    if any(bar.volume <= 0 or side * float(bar.close) <= level for bar in leg):
        return
    # The third-largest observation is the upper 5% boundary of a 60-minute sample.
    high_volume = sorted(float(b.volume) for b in background)[-3]
    ranges = [float(max(b.high, prev.close) - min(b.low, prev.close)) for prev, b in zip(background, background[1:])]
    high_range = sorted(ranges)[-3]
    first = leg[0]
    origin = side * float(first.open)
    first_close = side * float(first.close)
    volume = 0.0
    high, low = float(first.high), float(first.low)
    for i, b in enumerate(leg):
        close = side * float(b.close)
        high, low = max(high, float(b.high)), min(low, float(b.low))
        volume += float(b.volume)
        when = (b.bar_time + MINUTE).isoformat()
        if when < branch["confirmed_at"] or high <= low:
            continue
        body = (close - origin) / scale
        if i == 0:
            if body < 1 or (close - level) / scale < 0.75:
                continue
            reason = "强突破"
        else:
            if close <= side * float(leg[i - 1].close) or close - first_close < 0.15 * scale:
                continue
            reason = "守位续推"
        distance = (close - edge) / scale
        ratio = volume / ((i + 1) * normal_volume)
        position = (close - (low if side > 0 else -high)) / (high - low)
        if close - origin < 1.5 * high_range or volume / (i + 1) < 3 * high_volume:
            continue
        if distance < 0.5 or ratio < 1.5 or position < 0.8:
            continue
        score = (35 * min(1, distance / 1.25) + 25 * min(1, max(0, body) / 1.5)
                 + 20 * position + 20 * min(1, ratio / 2.5))
        if score >= ALERT_THRESHOLD:
            branch.update(breakout_alert_at=when, breakout_alert_reason=reason, breakout_alert_score=round(score, 1))
            branch["breakout_alert_context"] = {"hour_edge": side * edge, "distance_atr": distance, "volume_ratio": ratio}
            return


def annotate_breakouts(branches, ordered):
    indices = {b.bar_time: i for i, b in enumerate(ordered)}
    for branch in branches:
        if branch["kind"] in BREAKOUT_KINDS and not branch.get("superseded_by"):
            start = indices.get(datetime.fromisoformat(branch["started_at"]) - MINUTE)
            if start is not None:
                score_breakout(branch, ordered, start)
