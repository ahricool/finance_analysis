"""Frozen pre-break levels. Only uninterrupted, observed session minutes establish a break."""

from datetime import timedelta

from finance_analysis.intraday_options.analysis_window import observed
from finance_analysis.intraday_options.rules import RULES
from finance_analysis.intraday_options.structure import metrics, observed_atr, pivots

MINUTE = timedelta(minutes=1)


def breakout_seeds(ordered, opening, settings, snapshots=None):
    """Yield first qualifying closes per level; a gap ends knowledge of untouched levels."""
    if not settings.opening_enabled and not settings.pivot_enabled and not settings.midday_wave_enabled:
        return
    levels = []
    run = []
    volatility_window = []
    midday_active_until = {}
    n = settings.opening_minutes
    end = ordered[-1].bar_time
    # Opening and midday wave breakouts replay from session open to preserve exact rolling identity.
    if settings.opening_enabled or settings.midday_wave_enabled:
        start = opening
    else:
        start = max(
            opening,
            end - (settings.level_minutes + settings.pivot_atr_period + 2 + RULES["pivot_breakout"].lifetime) * MINUTE,
        )
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

        elapsed_minutes = (bar.bar_time - opening) / MINUTE
        if (
            settings.midday_wave_enabled
            and settings.midday_start_minutes <= elapsed_minutes <= settings.midday_end_minutes
            and len(run) >= settings.midday_min_bars
        ):
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
        seeds = []
        if settings.opening_enabled and len(run) == n and run[0].bar_time == opening:
            high, low = max(float(b.high) for b in run), min(float(b.low) for b in run)
            first_open = float(run[0].open)
            width = high - low
            if first_open > 0 and width / first_open >= settings.opening_min_range_pct:
                scale, samples = observed_atr(run, minimum=n - 1)
                seeds = [("opening_breakout", side, price, run, scale, samples, width)
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
            level_minutes = settings.opening_level_minutes if kind == "opening_breakout" else settings.level_minutes
            until = frozen + level_minutes * MINUTE
            if snapshots is not None and end < until + RULES[kind].lifetime * MINUTE:
                snapshots[identity] = dict(trigger=trigger, width=width, atr=scale,
                                           expires_at=(until + RULES[kind].lifetime * MINUTE).isoformat())
            levels.append(dict(identity=identity, kind=kind, side=side, trigger=trigger, atr=scale, atr_samples=samples,
                               structure_start=evidence[0].bar_time if width is not None else group[0].bar_time,
                               frozen=frozen, available=available, last_receipt=available,
                               until=until, width=width))
