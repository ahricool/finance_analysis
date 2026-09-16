"""Pure features aligned to explicit exchange sessions; never forward-fill gaps."""

import math
from statistics import fmean


def aligned_closes(bars, sessions):
    indexed = {b.trade_date: b for b in bars}
    if len(indexed) != len(bars):
        raise ValueError("Duplicate daily bars")
    values = [indexed[d].close if d in indexed else None for d in sessions]
    if any(v is None or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Incomplete or invalid session closes")
    return values


def index_features(bars, benchmark_bars, sessions):
    if len(sessions) != 21:
        raise ValueError("Exactly 21 sessions required")
    prices = aligned_closes(bars, sessions)
    benchmark = aligned_closes(benchmark_bars, sessions)
    result = {"close": prices[-1], "ret_1d": prices[-1] / prices[-2] - 1}
    for n in (5, 10, 20):
        result[f"ret_{n}d"] = prices[-1] / prices[-n - 1] - 1
        result[f"rs_{n}d"] = result[f"ret_{n}d"] - (benchmark[-1] / benchmark[-n - 1] - 1)
    result["previous_5d_return"] = prices[-6] / prices[-11] - 1
    result["momentum_acceleration_5d"] = result["ret_5d"] - result["previous_5d_return"]
    indexed = {b.trade_date: b for b in bars}
    amounts = [indexed[d].amount for d in sessions[-20:]]
    if any(v is None or not math.isfinite(v) or v < 0 for v in amounts) or sum(amounts) <= 0:
        raise ValueError("Incomplete or invalid index turnover")
    result["turnover_ratio_5d"] = fmean(amounts[-5:]) / fmean(amounts)
    return result


def constituent_observations(members, histories, sessions):
    """Complete 20-session members share the same denominator for all breadth metrics."""
    rows = []
    for member in members:
        code = member["thscode"]
        row = {
            "code": code,
            "name": member["name"],
            "price": None,
            "change_pct": None,
            "volume": None,
            "amount": None,
            "above_ma5": None,
            "above_ma20": None,
        }
        try:
            bars = histories.get(code, [])
            prices = aligned_closes(bars, sessions[-20:])
            bar = next(b for b in bars if b.trade_date == sessions[-1])
            row.update(
                price=prices[-1],
                change_pct=prices[-1] / prices[-2] - 1,
                volume=finite_nonnegative(bar.volume),
                amount=finite_nonnegative(bar.amount),
                above_ma5=prices[-1] > fmean(prices[-5:]),
                above_ma20=prices[-1] > fmean(prices),
            )
        except ValueError:
            pass
        rows.append(row)
    return sorted(rows, key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0), r["code"]))


def breadth(rows):
    valid = [r for r in rows if r["change_pct"] is not None]
    count = len(valid)
    up = sum(r["change_pct"] > 0 for r in valid)
    down = sum(r["change_pct"] < 0 for r in valid)
    return {
        "constituent_count": len(rows),
        "valid_constituent_count": count,
        "up_count": up,
        "down_count": down,
        "flat_count": count - up - down,
        "up_ratio": up / count if count else None,
        "above_ma5_ratio": sum(r["above_ma5"] for r in valid) / count if count else None,
        "above_ma20_ratio": sum(r["above_ma20"] for r in valid) / count if count else None,
        "equal_weight_return": fmean(r["change_pct"] for r in valid) if count else None,
    }


def finite_nonnegative(value):
    return value if value is not None and math.isfinite(value) and value >= 0 else None
