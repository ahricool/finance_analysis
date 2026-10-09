"""Pure metrics. Missing evidence stays null; percentiles use only earlier comparable sessions."""

from math import log, sqrt, isfinite
from statistics import stdev


def spread(bid, ask):
    if bid is None or ask is None or not isfinite(bid) or not isfinite(ask) or bid < 0 or ask <= 0 or ask < bid:
        return None
    return (ask - bid) / ((ask + bid) / 2)


def volume_oi(volume, oi, config):
    if (
        volume is None
        or oi is None
        or not isfinite(volume)
        or not isfinite(oi)
        or volume < config.min_volume
        or oi < config.min_oi
    ):
        return None
    return volume / oi


def percentile(value, history, minimum):
    values = [v for v in history if v is not None]
    if value is None or len(values) < minimum:
        return None
    # Midrank handles ties; constant volume is not a 100th percentile anomaly.
    return 100 * (sum(v < value for v in values) + 0.5 * sum(v == value for v in values)) / len(values)


def weighted_score(values, weights, method, reason=None):
    available = [(value, weight) for value, weight in zip(values, weights) if value is not None]
    return {
        "value": round(sum(v * w for v, w in available) / sum(w for _, w in available), 1) if available else None,
        "method": method,
        "evidence_count": len(available),
        "confidence": "medium" if len(available) >= 3 and method == "historical_percentiles" else "low",
        "reason": reason if not available else None,
        "components": values,
    }


def quote_status(row, now, config):
    if spread(row.bid, row.ask) is None:
        return "invalid_quote"
    if row.quote_timestamp is None:
        return "quote_timestamp_unknown"
    age = (now - row.quote_timestamp).total_seconds()
    if age < 0 or age > config.quote_max_age:
        return "stale_quote"
    if row.feed_type == "indicative":
        return "indicative_not_nbbo"
    return "valid"


def liquidity(row, now, session_date, config):
    relative = spread(row.bid, row.ask)
    status = quote_status(row, now, config)
    mid = (row.bid + row.ask) / 2 if relative is not None else None
    dte = (row.expiration - session_date).days
    notes = [status] if status != "valid" else []
    if row.bid == 0:
        notes.append("zero_bid")
    if mid is not None and mid < config.low_premium:
        notes.append("very_low_premium")
    if dte <= config.near_expiry_days:
        notes.append("near_expiry")
    moneyness = (
        row.strike / row.underlying_price
        if row.underlying_price is not None and isfinite(row.underlying_price) and row.underlying_price > 0
        else None
    )
    if moneyness is None:
        notes.append("underlying_price_missing")
    if (
        moneyness
        and row.quote_timestamp
        and row.underlying_timestamp
        and abs((row.quote_timestamp - row.underlying_timestamp).total_seconds()) > config.timestamp_tolerance
    ):
        notes.append("underlying_quote_time_mismatch")
        moneyness = None  # Do not mix stale underlying prices into current spread calibration.
    if moneyness and (
        (row.option_type == "call" and moneyness > config.deep_otm_call)
        or (row.option_type == "put" and moneyness < config.deep_otm_put)
    ):
        notes.append("deep_otm")
    # Initial rule scales spread tolerance by price, DTE and moneyness; no universal threshold.
    allowance = max(config.spread_base, config.spread_floor_dollars / mid) if mid else None
    if allowance and dte <= config.near_expiry_days:
        allowance *= config.near_expiry_spread_factor
    if allowance and moneyness:
        allowance *= 1 + abs(log(moneyness))
    components = [
        min(100, 50 * relative / allowance) if allowance else None,
        100 * (now - row.quote_timestamp).total_seconds() / config.quote_max_age if row.quote_timestamp else None,
        (
            100 * config.min_volume / (config.min_volume + row.volume)
            if row.volume is not None and row.volume_date == session_date
            else None
        ),
        100 * config.min_oi / (config.min_oi + row.open_interest) if row.open_interest is not None else None,
        (
            100 * config.low_depth / (config.low_depth + min(row.bid_size, row.ask_size))
            if row.bid_size is not None and row.ask_size is not None
            else None
        ),
    ]
    score = weighted_score(
        components if status == "valid" else [], config.liquidity_weights, "initial_price_dte_moneyness_rules", status
    )
    # Research proxy from the observed chain. Indicative/undated quotes are explicitly
    # low confidence; stale *dated* quotes from prior sessions must remain unavailable.
    from finance_analysis.market_review.trading_calendar import get_market_now

    same_session = row.quote_timestamp is not None and get_market_now("us", row.quote_timestamp).date() == session_date
    observed_usable = relative is not None and (
        row.quote_timestamp is None or same_session and row.quote_timestamp <= now
    )
    observed_score = weighted_score(
        [components[0], None, *components[2:]] if observed_usable else [],
        config.liquidity_weights,
        "observed_quote_liquidity_rules",
        "observed_quotes_unavailable",
    )
    return {
        "spread": relative,
        "mid": mid,
        "spread_allowance": allowance,
        "quote_status": status,
        "risk": score,
        "observed_risk": observed_score,
        "notes": notes,
        "volume_oi": volume_oi(row.volume, row.open_interest, config) if row.volume_date == session_date else None,
    }


def iv_usable(row, now, config):
    if row.iv is None or row.iv < config.min_iv or row.iv > config.max_iv:
        return False
    if row.data_source != "alpaca":
        # Yahoo's zero/zero quotes frequently accompany placeholder IVs; don't build an ATM index from them.
        return spread(row.bid, row.ask) is not None
    if row.quote_timestamp is None or row.quote_timestamp > now:
        return False
    from finance_analysis.market_review.trading_calendar import get_market_now, get_market_session_bounds

    observed_day = get_market_now("us", row.quote_timestamp).date()
    try:
        opened, closed = get_market_session_bounds("us", observed_day)
    except ValueError:
        return False
    # After-close IV is a daily observation, not a realtime liquidity quote.
    return (now - row.quote_timestamp).total_seconds() <= config.quote_max_age or (
        now >= closed
        and opened <= row.quote_timestamp <= closed
        and (now - closed).total_seconds() <= config.daily_iv_max_age
    )


def delta_iv(rows, kind, target, now, config):
    # Same source/feed/expiry is enforced by caller. Do not extrapolate beyond observed deltas.
    points = []
    for row in rows:
        if row.option_type != kind or row.delta is None or not iv_usable(row, now, config):
            continue
        if kind == "put" and not -1 <= row.delta < 0 or kind == "call" and not 0 < row.delta <= 1:
            continue
        # For timestamp-less daily IV retain its limitation; stale known quotes disqualify Alpaca Greeks.
        points.append((abs(row.delta), row.iv, row))
    points.sort(key=lambda p: p[0])
    for delta, iv, row in points:
        if abs(delta - target) < 1e-6:
            return iv, [row]
    for left, right in zip(points, points[1:]):
        if left[0] < target < right[0]:
            times = [p[2].iv_timestamp or p[2].quote_timestamp for p in (left, right)]
            if all(times) and abs((times[0] - times[1]).total_seconds()) > config.timestamp_tolerance:
                continue
            weight = (target - left[0]) / (right[0] - left[0])
            return left[1] + weight * (right[1] - left[1]), [left[2], right[2]]
    return None, []


def skew_25(rows, now, config):
    if len({(r.expiration, r.data_source, r.feed_type) for r in rows}) != 1:
        return None
    put, put_rows = delta_iv(rows, "put", 0.25, now, config)
    call, call_rows = delta_iv(rows, "call", 0.25, now, config)
    if put is None or call is None:
        return None
    times = [r.iv_timestamp or r.quote_timestamp for r in put_rows + call_rows]
    if all(times) and (max(times) - min(times)).total_seconds() > config.timestamp_tolerance:
        return None
    return put - call


def cohort(row, session_date):
    dte = (row.expiration - session_date).days
    dte_bucket = next((i for i, limit in enumerate((7, 21, 45, 90, 180)) if dte <= limit), 5)
    # Moneyness buckets avoid shifting strikes; use consistent moneyness even when some feeds supply delta.
    if not row.underlying_price or not isfinite(row.underlying_price) or row.underlying_price <= 0:
        return None
    m = row.strike / row.underlying_price
    money_bucket = next((i for i, limit in enumerate((0.9, 0.97, 1.03, 1.1)) if m <= limit), 4)
    return row.option_type, dte_bucket, money_bucket, row.data_source, row.feed_type


def realized_volatility(closes):
    if len(closes) < 21 or any(p is None or p <= 0 for p in closes[-21:]):
        return None
    returns = [log(b / a) for a, b in zip(closes[-21:], closes[-20:])]
    return stdev(returns) * sqrt(252)


def standard_iv(term, target=30):
    points = sorted((item["dte"], item["atm_iv"]) for item in term if item["atm_iv"] is not None)
    for dte, iv in points:
        if dte == target:
            return iv, "exact_expiry"
    for (d1, v1), (d2, v2) in zip(points, points[1:]):
        if d1 < target < d2:
            weight = (target - d1) / (d2 - d1)
            # Linear total variance interpolation, year basis ACT/365.
            return sqrt(((1 - weight) * v1 * v1 * d1 + weight * v2 * v2 * d2) / target), "total_variance_interpolation"
    return None, "requires_expiries_bracketing_30d"


def term_metrics(rows, session_date, now, config):
    result = []
    for expiration in sorted({r.expiration for r in rows}):
        group = [r for r in rows if r.expiration == expiration]
        spot = next(
            (
                r.underlying_price
                for r in group
                if r.underlying_price is not None and isfinite(r.underlying_price) and r.underlying_price > 0
            ),
            None,
        )
        if not spot:
            continue
        # Same strike ATM straddle and IV; no mismatched call/put strikes.
        pairs = []
        for strike in {r.strike for r in group}:
            call = next((r for r in group if r.strike == strike and r.option_type == "call"), None)
            put = next((r for r in group if r.strike == strike and r.option_type == "put"), None)
            if call and put and abs(log(strike / spot)) <= config.atm_moneyness_tolerance:
                pairs.append((abs(strike - spot), call, put))
        atm_iv, straddle = None, None
        iv_pairs, quote_pairs = [], []
        for pair in pairs:
            if all(iv_usable(r, now, config) for r in pair[1:]):
                times = [r.iv_timestamp or r.quote_timestamp for r in pair[1:]]
                if not all(times) or abs((times[0] - times[1]).total_seconds()) <= config.timestamp_tolerance:
                    iv_pairs.append(pair)
            if all(quote_status(r, now, config) == "valid" and r.bid > 0 for r in pair[1:]):
                call, put = pair[1:]
                if abs((call.quote_timestamp - put.quote_timestamp).total_seconds()) <= config.timestamp_tolerance:
                    quote_pairs.append(pair)
        if iv_pairs:
            _, call, put = min(iv_pairs, key=lambda pair: pair[0])
            atm_iv = (call.iv + put.iv) / 2
        if quote_pairs:
            _, call, put = min(quote_pairs, key=lambda pair: pair[0])
            straddle = (call.bid + call.ask + put.bid + put.ask) / 2
        dte = (expiration - session_date).days
        result.append(
            {
                "expiration": expiration.isoformat(),
                "dte": dte,
                "atm_iv": atm_iv,
                "skew_25": skew_25(group, now, config),
                "straddle_mid": straddle,
                "expected_move": (
                    straddle
                    if straddle is not None
                    else (spot * atm_iv * sqrt(dte / 365) if atm_iv and dte > 0 else None)
                ),
                "expected_move_method": "atm_straddle_mid" if straddle is not None else "iv_sqrt_act365",
                "source": group[0].data_source,
                "feed_type": group[0].feed_type,
                "iv_time_basis": (
                    "provider_timestamp" if all(r.iv_timestamp for r in group) else "observed_chain_time_unknown"
                ),
            }
        )
    return result


def oi_change(current, previous, previous_session, observed_at):
    """Dated, same-provider adjacent OI only; no intraday opening inference."""
    if not previous or current.oi_date is None or previous.oi_date != previous_session:
        return None
    from finance_analysis.market_review.trading_calendar import get_market_now

    if current.oi_date <= previous.oi_date or current.oi_date > get_market_now("us", observed_at).date():
        return None
    if (current.data_source, current.feed_type, current.symbol) != (
        previous.data_source,
        previous.feed_type,
        previous.symbol,
    ):
        return None
    if current.open_interest is None or previous.open_interest is None:
        return None
    return {
        "change": current.open_interest - previous.open_interest,
        "previous": previous.open_interest,
        "oi_date": current.oi_date.isoformat(),
        "previous_oi_date": previous.oi_date.isoformat(),
        "known_at": observed_at.isoformat(),
        "source": current.data_source,
        "feed_type": current.feed_type,
    }
