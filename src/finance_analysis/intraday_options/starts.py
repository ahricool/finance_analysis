"""Frozen pre-break levels. Only uninterrupted, observed session minutes establish a break."""

from datetime import timedelta

from finance_analysis.intraday_options.analysis_window import observed
from finance_analysis.intraday_options.rules import RULES
from finance_analysis.intraday_options.structure import metrics, observed_atr, pivots

MINUTE = timedelta(minutes=1)


def breakout_seeds(ordered, settings, snapshots=None):
    """Yield qualifying closes per level; a gap ends knowledge of untouched levels."""
    if not settings.pivot_enabled and not settings.midday_wave_enabled:
        return
    levels = []
    run = []
    volatility_window = []
    midday_active_until = {}
    end = ordered[-1].bar_time
    for bar in ordered:
        volatility_window = [b for b in volatility_window if b.bar_time >= bar.bar_time - settings.pivot_atr_period * MINUTE]
        if run and bar.bar_time - run[-1].bar_time != MINUTE:
            levels.clear()
            run.clear()
            volatility_window.clear()
            midday_active_until.clear()
        if not observed(bar) or not bar.is_valid() or bar.partial or bar.sampled:
            levels.clear()
            run.clear()
            volatility_window.clear()
            midday_active_until.clear()
            continue

        # Consume every crossed level, even if a late revision disqualifies its evidence.
        crossed = {}
        for level in levels[:]:
            kind, side, trigger = level["kind"], level["side"], level["trigger"]
            confirm_atr = RULES[kind].confirm_atr
            if bar.bar_time >= level["until"]:
                levels.remove(level)
            elif (float(bar.close) - trigger) * side > confirm_atr * level["atr"]:
                levels.remove(level)
                if (level["last_receipt"] <= max(bar.received_at, bar.bar_time + MINUTE)
                        and level["available"] <= bar.bar_time + MINUTE):
                    crossed[kind, side] = level  # Most recently confirmed swing if one K crosses several.
            else:
                level["last_receipt"] = max(level["last_receipt"], bar.received_at)
        for level in crossed.values():
            if end - bar.bar_time < RULES[level["kind"]].lifetime * MINUTE:
                yield level, bar

        if settings.midday_wave_enabled and len(run) >= settings.midday_min_bars:
            prior = run[-settings.midday_window_minutes:]
            ref_close = float(prior[-1].close)
            hi = max(float(b.high) for b in prior)
            lo = min(float(b.low) for b in prior)
            width = hi - lo
            if (
                ref_close > 0
                and settings.midday_min_width_pct <= width / ref_close <= settings.midday_max_width_pct
                and metrics(prior)[2] <= settings.midday_max_efficiency
            ):
                scale, samples = observed_atr(
                    prior, period=settings.pivot_atr_period, minimum=settings.pivot_atr_minimum
                )
                if scale:
                    rule = RULES["midday_wave_breakout"]
                    bar_close = float(bar.close)
                    when = bar.bar_time + MINUTE
                    for side, trigger in ((1, hi), (-1, lo)):
                        active_until = midday_active_until.get(side)
                        if active_until is not None and when < active_until:
                            continue
                        if (bar_close - trigger) * side > rule.confirm_atr * scale:
                            available = max(bar.bar_time, *(b.received_at for b in prior))
                            if available > max(bar.received_at, when):
                                continue
                            expires = when + rule.lifetime * MINUTE
                            midday_active_until[side] = expires
                            identity = (
                                f"midday_wave_breakout:{side}:"
                                f"{prior[0].bar_time.isoformat()}:{when.isoformat()}"
                            )
                            if snapshots is not None and end < expires:
                                snapshots[identity] = dict(
                                    trigger=trigger, width=width, atr=scale, expires_at=expires.isoformat()
                                )
                            if end - bar.bar_time < rule.lifetime * MINUTE:
                                yield dict(
                                    identity=identity,
                                    kind="midday_wave_breakout",
                                    side=side,
                                    trigger=trigger,
                                    atr=scale,
                                    atr_samples=samples,
                                    structure_start=prior[0].bar_time,
                                    frozen=bar.bar_time,
                                    available=available,
                                    last_receipt=max(available, bar.received_at),
                                    until=expires,
                                    width=width,
                                ), bar

        run.append(bar)
        volatility_window.append(bar)
        group = run[-5:]
        if not settings.pivot_enabled or len(group) < 5:
            continue
        for point in pivots(group):
            scale, samples = observed_atr(volatility_window, period=settings.pivot_atr_period,
                                          minimum=settings.pivot_atr_minimum)
            if not scale:
                continue
            kind = "pivot_breakout"
            side = 1 if point["kind"] == "high" else -1
            frozen = bar.bar_time + MINUTE
            available = max(frozen, *(b.received_at for b in volatility_window))
            identity = f"{kind}:{side}:{group[2].bar_time.isoformat()}:{frozen.isoformat()}"
            until = frozen + settings.level_minutes * MINUTE
            if snapshots is not None and end < until + RULES[kind].lifetime * MINUTE:
                snapshots[identity] = dict(trigger=point["price"], width=None, atr=scale,
                                           expires_at=(until + RULES[kind].lifetime * MINUTE).isoformat())
            levels.append(dict(identity=identity, kind=kind, side=side, trigger=point["price"], atr=scale,
                               atr_samples=samples, structure_start=group[0].bar_time, frozen=frozen,
                               available=available, last_receipt=available, until=until, width=None))
