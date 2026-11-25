"""Frozen pre-break levels. Only uninterrupted, observed session minutes establish a break."""

from datetime import timedelta

from finance_analysis.intraday_options.analysis_window import observed
from finance_analysis.intraday_options.rules import RULES
from finance_analysis.intraday_options.structure import metrics, observed_atr, pivots, sanitize_opening_bar

MINUTE = timedelta(minutes=1)


def _use_opening_drive_mode(settings):
    """V7 clean opening-drive mode evaluates causal efficiency/momentum across [min_elapsed..end]."""
    return settings.opening_enabled and (
        settings.opening_min_efficiency > 0 or settings.opening_min_elapsed_minutes > settings.opening_minutes
    )


def breakout_seeds(ordered, opening, settings, snapshots=None):
    """Yield qualifying closes per level; a gap ends knowledge of untouched levels."""
    if not settings.opening_enabled and not settings.pivot_enabled and not settings.midday_wave_enabled:
        return
    levels = []
    run = []
    volatility_window = []
    midday_active_until = {}
    session_hi = None
    session_lo = None
    session_max_receipt = None
    opening_drive_mode = _use_opening_drive_mode(settings)
    or_state = None
    drive_cum_path = 0.0
    drive_prev_close = None
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
            or_state = None
            drive_cum_path = 0.0
            drive_prev_close = None
        if not observed(bar) or not bar.is_valid() or bar.partial or bar.sampled:
            levels.clear()
            run.clear()
            or_state = None
            drive_cum_path = 0.0
            drive_prev_close = None
            continue
        bar, _ = sanitize_opening_bar(bar, opening, settings.opening_bar_max_wick_pct)

        # Consume every crossed level, even if a late revision disqualifies its evidence.
        crossed = {}
        for level in levels[:]:
            kind, side, trigger = level["kind"], level["side"], level["trigger"]
            confirm_atr = 0.20 if kind == "opening_breakout" else RULES[kind].confirm_atr
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

        elapsed_minutes = (bar.bar_time - opening) / MINUTE
        if (
            settings.midday_wave_enabled
            and settings.midday_start_minutes <= elapsed_minutes < settings.midday_end_minutes
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
                        if settings.midday_require_session_extreme:
                            tol = settings.midday_session_extreme_tolerance
                            if side == 1 and session_hi is not None and hi < session_hi * (1.0 - tol):
                                continue
                            if side == -1 and session_lo is not None and lo > session_lo * (1.0 + tol):
                                continue
                        if (bar_close - trigger) * side > rule.confirm_atr * scale:
                            available = max(bar.bar_time, *(b.received_at for b in prior))
                            if settings.midday_require_session_extreme and session_max_receipt is not None:
                                available = max(available, session_max_receipt)
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
        bar_hi, bar_lo = float(bar.high), float(bar.low)
        bar_open, bar_close = float(bar.open), float(bar.close)
        if len(run) == 1 and run[0].bar_time == opening:
            drive_cum_path = abs(bar_close - bar_open)
            drive_prev_close = bar_close
        elif drive_prev_close is not None:
            drive_cum_path += abs(bar_close - drive_prev_close)
            drive_prev_close = bar_close
        session_hi = bar_hi if session_hi is None else max(session_hi, bar_hi)
        session_lo = bar_lo if session_lo is None else min(session_lo, bar_lo)
        session_max_receipt = (
            bar.received_at if session_max_receipt is None else max(session_max_receipt, bar.received_at)
        )
        group = run[-5:]
        seeds = []
        if settings.opening_enabled and len(run) == n and run[0].bar_time == opening:
            high, low = max(float(b.high) for b in run), min(float(b.low) for b in run)
            first_open = float(run[0].open)
            width = high - low
            if first_open > 0 and width / first_open >= settings.opening_min_range_pct:
                scale, samples = observed_atr(run, minimum=n - 1)
                if opening_drive_mode:
                    if scale:
                        or_frozen = bar.bar_time + MINUTE
                        or_available = max(or_frozen, *(b.received_at for b in run))
                        or_state = dict(
                            high=high,
                            low=low,
                            first_open=first_open,
                            width=width,
                            atr=scale,
                            atr_samples=samples,
                            frozen=or_frozen,
                            available=or_available,
                        )
                        if snapshots is not None:
                            or_exp = opening + (
                                settings.opening_end_minutes + RULES["opening_breakout"].lifetime
                            ) * MINUTE
                            if end < or_exp:
                                for s_dir, s_lvl in ((1, high), (-1, low)):
                                    snapshots[f"opening_range:{s_dir}:{opening.isoformat()}"] = dict(
                                        trigger=s_lvl, width=width, atr=scale, expires_at=or_exp.isoformat()
                                    )
                else:
                    seeds = [
                        ("opening_breakout", side, price, run, scale, samples, width)
                        for side, price in ((1, high), (-1, low))
                    ]
        if (
            opening_drive_mode
            and or_state is not None
            and bar.bar_time == end
            and run[0].bar_time == opening
        ):
            elapsed_close = int((bar.bar_time + MINUTE - opening) / MINUTE)
            if settings.opening_min_elapsed_minutes <= elapsed_close < settings.opening_end_minutes:
                when = bar.bar_time + MINUTE
                first_open = or_state["first_open"]
                open_eff = abs(bar_close - first_open) / drive_cum_path if drive_cum_path > 0 else 0.0
                if open_eff >= settings.opening_min_efficiency - 1e-12:
                    available = max(when, or_state["available"], session_max_receipt)
                    rule = RULES["opening_breakout"]
                    expires = min(when + rule.lifetime * MINUTE, opening + settings.opening_end_minutes * MINUTE)
                    for side, trigger in ((1, or_state["high"]), (-1, or_state["low"])):
                        if (bar_close - trigger) * side <= rule.confirm_atr * or_state["atr"]:
                            continue
                        if settings.opening_require_directional_bar and (bar_close - bar_open) * side <= 0:
                            continue
                        sym_ret = (bar_close / first_open - 1.0) * side
                        if settings.min_open_move > 0 and sym_ret < settings.min_open_move - 1e-12:
                            continue
                        identity = f"opening_breakout:{side}:{opening.isoformat()}:{when.isoformat()}"
                        process_id = f"opening_breakout:{side}:{opening.isoformat()}"
                        yield dict(
                            identity=identity,
                            process_id=process_id,
                            kind="opening_breakout",
                            side=side,
                            trigger=trigger,
                            atr=or_state["atr"],
                            atr_samples=or_state["atr_samples"],
                            structure_start=opening,
                            frozen=or_state["frozen"],
                            available=available,
                            last_receipt=available,
                            until=expires,
                            width=or_state["width"],
                            opening_drive=True,
                            open_efficiency=open_eff,
                        ), bar
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
