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
    """Daily, MA5 and MA20 use independent windows ending at the same session."""
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
        bars = histories.get(code, [])
        for window, field in ((2, "change_pct"), (5, "above_ma5"), (20, "above_ma20")):
            try:
                if len(sessions) < window:
                    continue
                prices = aligned_closes(bars, sessions[-window:])
                row[field] = prices[-1] / prices[-2] - 1 if window == 2 else prices[-1] > fmean(prices)
                bar = next(b for b in bars if b.trade_date == sessions[-1])
                row.update(price=prices[-1], volume=finite_nonnegative(bar.volume), amount=finite_nonnegative(bar.amount))
            except ValueError:
                pass
        rows.append(row)
    return sorted(rows, key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0), r["code"]))


def breadth(rows, minimum_coverage=0.0):
    daily = [r for r in rows if r["change_pct"] is not None]
    ma5 = [r for r in rows if r["above_ma5"] is not None]
    ma20 = [r for r in rows if r["above_ma20"] is not None]
    total, count = len(rows), len(daily)
    up = sum(r["change_pct"] > 0 for r in daily)
    down = sum(r["change_pct"] < 0 for r in daily)
    above5 = sum(r["above_ma5"] for r in ma5)
    above20 = sum(r["above_ma20"] for r in ma20)
    coverage = {
        "daily_breadth_coverage": count / total if total else 0.0,
        "ma5_coverage": len(ma5) / total if total else 0.0,
        "ma20_coverage": len(ma20) / total if total else 0.0,
    }
    def usable(n):
        return bool(n and total and n / total >= minimum_coverage)

    return {
        "constituent_count": total,
        "daily_valid_count": count,
        "up_count": up,
        "down_count": down,
        "flat_count": count - up - down,
        "up_ratio": up / count if usable(count) else None,
        "equal_weight_return": fmean(r["change_pct"] for r in daily) if usable(count) else None,
        "ma5_valid_count": len(ma5),
        "above_ma5_count": above5,
        "above_ma5_ratio": above5 / len(ma5) if usable(len(ma5)) else None,
        "ma20_valid_count": len(ma20),
        "above_ma20_count": above20,
        "above_ma20_ratio": above20 / len(ma20) if usable(len(ma20)) else None,
        "quality": {**coverage, "breadth_status": "ok" if total and min(coverage.values()) == 1 else "partial"},
    }


def finite_nonnegative(value):
    return value if value is not None and math.isfinite(value) and value >= 0 else None
