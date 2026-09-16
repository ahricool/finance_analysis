"""Cross-sectional ranks: 1 strongest, ties share average percentile."""

from .config import DEFAULT_CONFIG


def percentiles(values):
    n = len(values)
    if n == 1:
        return [50.0]
    return [100 * (sum(x < v for x in values) + (sum(x == v for x in values) - 1) / 2) / (n - 1) for v in values]


def rank_rows(rows, history, prior_sessions, config=DEFAULT_CONFIG):
    for field in ("rs_5d", "rs_10d", "rs_20d", "momentum_acceleration_5d"):
        values = [r[field] for r in rows]
        for row, pct in zip(rows, percentiles(values)):
            if field == "momentum_acceleration_5d":
                row["acceleration_percentile"] = pct
            else:
                row[f"{field}_percentile"] = pct
                row[f"{field}_rank"] = 1 + sum(v > row[field] for v in values)
    for row in rows:
        row["strength_score"] = sum(row[f"rs_{n}d_percentile"] * w for n, w in config.weights)
    # Stable code ordering resolves composite ties, so rank 1 always exists.
    rows.sort(key=lambda r: (-r["strength_score"], r["industry_code"]))
    for rank, row in enumerate(rows, 1):
        row["strength_rank"] = rank
        for offset in (1, 3, 5):
            day = prior_sessions[-offset]
            previous = history.get((day, row["industry_code"]))
            row[f"rank_change_{offset}d"] = None if previous is None else previous["strength_rank"] - rank
    return rows
