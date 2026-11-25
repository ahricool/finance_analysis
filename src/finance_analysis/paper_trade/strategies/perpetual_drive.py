"""24/7 adaptation of intraday options V8 opening drive.

Independent signal and exit rules: no stock calendar, option contract or
intraday-options runtime dependency. All ratios are fractional, not percentages.
"""

from decimal import Decimal

TYPE = "perpetual_drive"
MINUTE = 60_000
PERIOD = 5 * MINUTE
HOUR = 60 * MINUTE
DAY = 24 * HOUR
BENCHMARK = "BTCUSDT"


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("NONFINITE_DRIVE_DATA")
    return result


def candle(row):
    o, h, low, c, volume, turnover = (
        decimal(row[k]) for k in ("open", "high", "low", "close", "volume", "turnover")
    )
    if not 0 < low <= min(o, c) <= max(o, c) <= h or volume < 0 or turnover < 0:
        raise ValueError("INVALID_DRIVE_CANDLE")
    if (volume == 0) != (turnover == 0):
        raise ValueError("INVALID_DRIVE_VOLUME")
    return o, h, low, c, volume, turnover


def closed_window(bars, start, end, now):
    indexed = {row["timestamp"]: row for row in bars}
    if now // MINUTE * MINUTE not in indexed:
        return None
    if any(t not in indexed or indexed[t].get("closed") is False for t in range(start, end, MINUTE)):
        return None
    return [candle(indexed[t]) for t in range(start, end, MINUTE)]


def daily_atr(bars, anchor):
    """ATR14 using the 15 consecutive confirmed UTC dates before the anchor."""
    day = anchor // DAY * DAY
    indexed = {row["timestamp"]: row for row in bars}
    stamps = list(range(day - 15 * DAY, day, DAY))
    if any(t not in indexed for t in stamps):
        return None
    rows = [candle(indexed[t]) for t in stamps]
    ranges = [max(h - low, abs(h - prev[3]), abs(low - prev[3]))
              for prev, (_, h, low, _, _, _) in zip(rows, rows[1:])]
    ratio = sum(ranges) / 14 / rows[-1][3]
    return min(Decimal("0.08"), max(Decimal("0.012"), ratio))


def exit_profile(atr, stop_pct):
    return {
        "atr": str(atr),
        "initial_stop": str(min(atr * Decimal("1.2"), decimal(stop_pct) / 100)),
        "tier1_trigger": str(atr * Decimal("0.5")),
        "tier1_lock": str(atr * Decimal("0.08")),
        "tier2_trigger": str(atr * Decimal("1.2")),
        "tier2_lock": str(atr * Decimal("0.6")),
    }


def valid_profile(profile, stop_pct):
    if not isinstance(profile, dict):
        return False
    try:
        atr = decimal(profile["atr"])
        if not Decimal("0.012") <= atr <= Decimal("0.08"):
            return False
        expected = exit_profile(atr, stop_pct)
        return all(decimal(profile[k]) == decimal(v) for k, v in expected.items())
    except (KeyError, ValueError, ArithmeticError):
        return False


def ratchet(profile, stage, entry, mark, signed_quantity):
    """Return monotonic tier and whether the current Demo mark breaches its lock."""
    entry, mark = decimal(entry), decimal(mark)
    if entry <= 0 or mark <= 0 or stage not in (0, 1, 2) or not signed_quantity:
        raise ValueError("INVALID_DRIVE_POSITION")
    move = (mark / entry - 1) * (1 if signed_quantity > 0 else -1)
    if move >= decimal(profile["tier2_trigger"]):
        stage = 2
    elif move >= decimal(profile["tier1_trigger"]):
        stage = max(1, stage)
    lock = decimal(profile[f"tier{stage}_lock"]) if stage else -decimal(profile["initial_stop"])
    return stage, move <= lock


def vwap(rows):
    volume = sum(row[4] for row in rows)
    return sum(row[5] for row in rows) / volume if volume else None


def qualifies(rows, market, config):
    """Port of V8 opening range, directional drive, efficiency and context filters."""
    opening = rows[0][0]
    # Ignore an anomalous first-minute wick outside the original 3% bound.
    first = rows[0]
    body_high, body_low = max(first[0], first[3]), min(first[0], first[3])
    first_high = body_high if (first[1] - body_high) / body_high > Decimal("0.03") else first[1]
    first_low = body_low if (body_low - first[2]) / body_low > Decimal("0.03") else first[2]
    high = max(first_high, *(r[1] for r in rows[1:5]))
    low = min(first_low, *(r[2] for r in rows[1:5]))
    width = (high - low) / opening
    if width < decimal(config.get("drive_range_pct", "0.8")) / 100:
        return None
    close = rows[-1][3]
    path = abs(first[3] - opening) + sum(abs(b[3] - a[3]) for a, b in zip(rows, rows[1:]))
    efficiency = abs(close - opening) / path if path else Decimal(0)
    average = vwap(rows)
    market_average = vwap(market)
    if efficiency < decimal(config.get("drive_efficiency", "0.48")) or average is None or market_average is None:
        return None
    side = 1 if close > high else -1 if close < low else 0
    if not side or (close - rows[-1][0]) * side <= 0 or (close - average) * side <= 0:
        return None
    move = (close / opening - 1) * side
    market_move = (market[-1][3] / market[0][0] - 1) * side
    relative = move - market_move
    if move < decimal(config.get("drive_move_pct", "1.2")) / 100:
        return None
    if market_move < decimal("0.0015") or (market[-1][3] - market_average) * side <= 0:
        return None
    if config["symbol"] != BENCHMARK and relative < decimal(config.get("drive_relative_pct", "0.8")) / 100:
        return None
    return "LONG" if side > 0 else "SHORT", {
        "range_pct": str(width * 100),
        "move_pct": str(move * 100),
        "efficiency": str(efficiency),
        "vwap": str(average),
        "benchmark_move_pct": str(market_move * 100),
        "relative_pct": str(relative * 100),
        "production_close": str(close),
        "range_high": str(high),
        "range_low": str(low),
    }


def evaluate(bars, benchmark, daily, now, config):
    """Only the first qualifying closed 5m decision in each causal hourly window.

    Overlapping hourly anchors last 120 minutes. The newest mature window wins
    if both first qualify together. Historical prefixes are warmup only.
    Returns (decision timestamp, direction, evidence), or None for missing data.
    """
    end = now // PERIOD * PERIOD
    if not 15_000 <= now - end <= 90_000:
        return None
    newest = (end - 12 * MINUTE) // HOUR * HOUR
    for anchor in (newest, newest - HOUR):
        if not 12 * MINUTE <= end - anchor < 120 * MINUTE:
            continue
        rows = closed_window(bars, anchor, end, now)
        market = closed_window(benchmark, anchor, end, now)
        if rows is None or market is None:
            return None
        atr = daily_atr(daily, anchor)
        if atr is None:
            return None
        # Review every previous eligible decision, never replay a missed drive.
        for count in range(15, len(rows) + 1, 5):
            result = qualifies(rows[:count], market[:count], config)
            if result is None:
                continue
            if count == len(rows):
                direction, evidence = result
                return end, direction, {
                    **evidence, "strategy_type": TYPE, "anchor": anchor,
                    "exit_profile": exit_profile(atr, config["stop_pct"]),
                }
            break
    return end, None, {}
