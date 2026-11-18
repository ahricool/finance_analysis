"""Frozen pre-break levels. Only uninterrupted, observed session minutes establish a break."""

from datetime import timedelta

from finance_analysis.intraday_options.analysis_window import observed
from finance_analysis.intraday_options.rules import RULES
from finance_analysis.intraday_options.structure import observed_atr, pivots

MINUTE = timedelta(minutes=1)


def breakout_seeds(ordered, opening, settings, snapshots=None):
    """Yield first qualifying closes per level; a gap ends knowledge of untouched levels."""
    if not settings.opening_enabled and not settings.pivot_enabled:
        return
    levels = []
    run = []
    volatility_window = []
    n = settings.opening_minutes
    end = ordered[-1].bar_time
    # A pivot only needs its local ATR history, level lifetime and execution lifetime.
    start = end - (settings.level_minutes + settings.pivot_atr_period + 2 + RULES["pivot_breakout"].lifetime) * MINUTE
    for bar in ordered:
        if bar.bar_time < start:
            continue
        volatility_window = [b for b in volatility_window if b.bar_time >= bar.bar_time - settings.pivot_atr_period * MINUTE]
        if run and bar.bar_time - run[-1].bar_time != MINUTE:
            levels.clear()
            run.clear()
        if not observed(bar) or not bar.is_valid() or bar.partial or bar.sampled:
            levels.clear()
            run.clear()
            continue

        # Consume every crossed level, even if a late revision disqualifies its evidence.
        crossed = {}
        for level in levels[:]:
            kind, side, trigger = level["kind"], level["side"], level["trigger"]
            if bar.bar_time >= level["until"]:
                levels.remove(level)
            elif (float(bar.close) - trigger) * side > RULES[kind].confirm_atr * level["atr"]:
                levels.remove(level)
                if (level["last_receipt"] <= max(bar.received_at, bar.bar_time + MINUTE)
                        and level["available"] <= bar.bar_time + MINUTE):
                    crossed[kind, side] = level  # Most recently confirmed swing if one K crosses several.
            else:
                level["last_receipt"] = max(level["last_receipt"], bar.received_at)
        for level in crossed.values():
            if end - bar.bar_time < RULES[level["kind"]].lifetime * MINUTE:
                yield level, bar

        run.append(bar)
        volatility_window.append(bar)
        group = run[-5:]
        seeds = []
        if settings.opening_enabled and len(run) == n and run[0].bar_time == opening:
            high, low = max(float(b.high) for b in run), min(float(b.low) for b in run)
            scale, samples = observed_atr(run, minimum=n - 1)
            seeds = [("opening_breakout", side, price, run, scale, samples, high - low)
                     for side, price in ((1, high), (-1, low))]
        if settings.pivot_enabled and len(group) == 5:
            for point in pivots(group):
                evidence = volatility_window
                scale, samples = observed_atr(evidence, period=settings.pivot_atr_period, minimum=settings.pivot_atr_minimum)
                seeds.append(("pivot_breakout", 1 if point["kind"] == "high" else -1,
                              point["price"], evidence, scale, samples, None))
        for kind, side, trigger, evidence, scale, samples, width in seeds:
            if not scale:
                continue
            frozen = bar.bar_time + MINUTE
            available = max(frozen, *(b.received_at for b in evidence))
            anchor = run[0].bar_time if width is not None else group[2].bar_time
            identity = f"{kind}:{side}:{anchor.isoformat()}:{frozen.isoformat()}"
            until = frozen + settings.level_minutes * MINUTE
            if snapshots is not None and end < until + RULES[kind].lifetime * MINUTE:
                snapshots[identity] = dict(trigger=trigger, width=width, atr=scale,
                                           expires_at=(until + RULES[kind].lifetime * MINUTE).isoformat())
            levels.append(dict(identity=identity, kind=kind, side=side, trigger=trigger, atr=scale, atr_samples=samples,
                               structure_start=evidence[0].bar_time if width is not None else group[0].bar_time,
                               frozen=frozen, available=available, last_receipt=available,
                               until=until, width=width))
