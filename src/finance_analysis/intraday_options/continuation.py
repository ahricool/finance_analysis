"""Small causal structure detectors. Identity starts at an observed counter-move."""

from datetime import datetime, timedelta

from finance_analysis.intraday_options.analysis_window import observed
from finance_analysis.intraday_options.rules import CONTINUATION as C, RULES
from finance_analysis.intraday_options.structure import metrics, observed_atr

MINUTE = timedelta(minutes=1)


def pullback_anchor(history, side, since=None, scale=0):
    """Two real advances followed by a non-advancing real close; never a sliding timestamp."""
    for i in range(len(history) - 1, 2, -1):
        group = history[i - 3:i + 1]
        if (not all(observed(b) for b in group)
                or any(b.bar_time - a.bar_time != MINUTE for a, b in zip(group, group[1:]))):
            continue
        if since and group[0].bar_time < datetime.fromisoformat(since):
            continue
        moves = [(float(b.close) - float(a.close)) * side for a, b in zip(group, group[1:])]
        # Once a later close has resumed beyond the pre-pullback close, this old
        # pause no longer identifies the current EMA touch / pullback.
        resumed = any(observed(b) and (float(b.close) - float(group[-2].close)) * side > 0
                      for b in history[i + 1:])
        if (not resumed and moves[0] > 0 and moves[1] > 0 and moves[2] <= 0
                and sum(moves[:2]) >= C.rearm_advance_atr * scale):
            return group[-1].bar_time.isoformat()
    return None


def setup(history, side):
    """Freeze the first three-bar pause after an impulse, using only pre-trigger evidence."""
    n = C.structure_bars
    if len(history) < C.minimum_background + n:
        return None, f"趋势延续等待至少{C.minimum_background}根真实背景K及{n}根真实整理K"
    recent = history[-n:]
    if (not all(observed(b) for b in recent)
            or recent[-1].bar_time - recent[0].bar_time != (n - 1) * MINUTE):
        return None, "趋势延续整理窗口需要连续真实闭合K，补平K不作为整理证据"
    background = [b for b in history[:-n] if b.bar_time >= recent[0].bar_time - C.background * MINUTE]
    real = [b for b in background if observed(b)]
    scale, samples = observed_atr(background, C.volatility_bars, C.minimum_volatility_samples)
    if len(real) < C.minimum_background or not scale:
        return None, f"趋势延续真实背景或相邻真实波动样本不足（至少{C.minimum_volatility_samples}个TR），不使用补平零波动"
    # The pause starts with an actual counter-move following an impulse. Sliding
    # the three-bar window cannot give consecutive falling candles new identities.
    anchor = pullback_anchor(background + recent[:1], side, scale=scale)
    if anchor != recent[0].bar_time.isoformat():
        return None, "尚无趋势推进后独立的反向停顿/浅回撤起点"
    slope, stability, efficiency = metrics(real)
    if (slope * side <= 0 or stability < C.stability or efficiency < C.efficiency
            or (float(real[-1].close) - float(real[0].close)) * side < C.advance_atr * scale):
        return None, "触发前真实背景尚无足够稳定性、路径效率和顺向推进"
    high, low = max(float(b.high) for b in recent), min(float(b.low) for b in recent)
    extreme = low if side > 0 else high
    depth = (float(real[-1].close) - extreme) * side / scale
    drift = (float(recent[-1].close) - float(recent[0].close)) * side / scale
    trend_guard = (min(float(b.low) for b in real[-C.trend_guard_bars:]) if side > 0
                   else max(float(b.high) for b in real[-C.trend_guard_bars:]))
    if ((high - low) / scale > C.width_atr or not 0 <= depth <= C.pullback_atr
            or drift > C.forward_drift_atr or (extreme - trend_guard) * side < 0):
        return None, "整理过宽、回撤过深、仍在单边推进或已破坏此前趋势"
    return dict(
        structure_start=anchor, structure_end=(recent[-1].bar_time + MINUTE).isoformat(),
        structure_high=high, structure_low=low, trigger=high if side > 0 else low,
        invalidation=extreme - side * C.stop_buffer_atr * scale, atr=scale,
        atr_source="observed_adjacent_true_ranges", atr_samples=samples,
        structure_quality=100 * (.5 * stability + .5 * efficiency),
        process_id=f"trend:{side}:{anchor}",
    ), None


def confirmation(branch, history):
    bar = history[-1]
    when = (bar.bar_time + MINUTE).isoformat()
    side = 1 if branch["direction"] == "bullish" else -1
    rule = RULES["trend_continuation"]
    if bar.bar_time.isoformat() < branch["structure_end"] or not observed(bar):
        return False, None, "等待整理之后真实闭合K突破"
    distance = (float(bar.close) - branch["trigger"]) * side / branch["atr"]
    if branch.get("triggered_at") is None:
        if (bar.bar_time + MINUTE - datetime.fromisoformat(branch["structure_start"])
                > C.maximum_structure_minutes * MINUTE):
            branch.update(status="expired")
            return False, None, f"整理超过{C.maximum_structure_minutes}分钟未突破，等待新的独立结构"
        if distance > rule.confirm_atr:
            branch["triggered_at"] = when
    if not branch.get("triggered_at"):
        return False, None, f"等待真实收盘突破冻结整理边界{rule.confirm_atr:g} ATR"
    span = float(bar.high - bar.low)
    # Both closes of ordinary confirmation must respect the breakout range cap.
    # A large second candle cannot evade the guard just because the first was small.
    if (not branch["confirmed_at"] and distance > rule.confirm_atr
            and span > C.maximum_break_range_atr * branch["atr"]):
        branch["breakout_rejection"] = f"突破K超过{C.maximum_break_range_atr:g} ATR，不追逐该长K过程"
    body = float(bar.close - bar.open) * side
    location = (float(bar.close - bar.low) if side > 0 else float(bar.high - bar.close)) / span if span else 0
    strong = (when == branch["triggered_at"] and span > 0 and distance >= C.strong_break_atr
              and body / span >= C.strong_body_fraction and location >= C.strong_close_location
              and span <= C.maximum_break_range_atr * branch["atr"])
    pair = history[-2:]
    normal = (len(pair) == 2 and pair[1].bar_time - pair[0].bar_time == MINUTE
              and (pair[0].bar_time + MINUTE).isoformat() >= branch["triggered_at"]
              and all(observed(b) and (float(b.close) - branch["trigger"]) * side
                      > rule.confirm_atr * branch["atr"] for b in pair))
    return strong or normal, "strong_break" if strong else "two_closes" if normal else None, (
        branch.get("breakout_rejection") or "等待两根真实收盘确认；强突破可用一根真实闭合K确认"
    )
