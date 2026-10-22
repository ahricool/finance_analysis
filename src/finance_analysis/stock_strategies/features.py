"""Bounded DB-only indicator windows, aligned to exchange sessions (gaps stay gaps)."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd


class DataNotReady(ValueError):
    """Retryable missing or incomplete persisted input."""


def finite(value):
    return value is not None and np.isfinite(value)


def regression(values):
    if not np.isfinite(values).all() or np.any(values <= 0):
        return np.nan
    y = np.log(values)
    x = np.arange(len(y), dtype=float)
    x -= x.mean()
    slope = np.dot(x, y - y.mean()) / np.dot(x, x)
    total = np.square(y - y.mean()).sum()
    r2 = np.dot(x, y - y.mean()) ** 2 / np.dot(x, x) / total if total > 0 else 0
    return float(np.expm1(np.clip(slope * 252, -10, 10)) * r2)


def smooth(values, window, alpha):
    output = []
    count, total, last = 0, 0.0, float("nan")
    for value in values:
        if not finite(value):
            count, total, last = 0, 0.0, float("nan")
        else:
            count += 1
            if count <= window:
                total += value
                if count == window:
                    last = total / window
            else:
                last = alpha * value + (1 - alpha) * last
        output.append(last)
    return np.asarray(output)


def wilder(values, window=14):
    return smooth(values, window, 1 / window)[-1]


def indicators(rows, sessions):
    fields = ["open", "high", "low", "close", "volume", "amount"]
    frame = pd.DataFrame(rows, columns=["date", *fields]).set_index("date").reindex(sessions)
    frame = frame.astype(float)
    c, h, lo, v = (frame[k] for k in ("close", "high", "low", "volume"))
    valid = (c > 0) & (h >= c) & (lo <= c) & (lo > 0) & (v > 0)
    c = c.where(valid)
    prev = c.shift()
    tr = pd.concat([h - lo, (h - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1, skipna=False).where(valid)
    result = {k: frame[k].iloc[-1] for k in fields}
    for n in (20, 50, 100, 200):
        result[f"ma{n}"] = c.rolling(n).mean().iloc[-1]
    result.update(
        valid=bool(valid.iloc[-1]),
        history_count=int(valid.sum()),
        previous_close=prev.iloc[-1],
        previous_high=h.shift().iloc[-1],
        mom60=c.pct_change(60, fill_method=None).iloc[-1],
        mom126=c.pct_change(126, fill_method=None).iloc[-1],
        atr=wilder(tr.to_numpy()),
        low20=lo.shift().rolling(20).min().iloc[-1],
        vol20=c.pct_change(fill_method=None).rolling(20).std(ddof=1).iloc[-1] * np.sqrt(252),
        liquidity=frame.amount.where(frame.amount > 0, c * v).rolling(20).mean().iloc[-1],
        regression=regression(c.iloc[-126:].to_numpy()) if len(c) >= 126 else np.nan,
        max_return=c.pct_change(fill_method=None).abs().rolling(126).max().iloc[-1],
    )
    ema50 = pd.Series(smooth(c.to_numpy(), 50, 2 / 51), index=c.index)
    result.update(
        ema50=ema50.iloc[-1],
        ema50_previous=ema50.shift(5).iloc[-1],
        force=smooth((c.diff() * v).to_numpy(), 2, 2 / 3)[-1],
    )
    from finance_analysis.trend_following.features import weighted_log_regression

    visible = c.iloc[-41:].to_numpy()
    if len(visible) == 41 and np.isfinite(visible).all() and np.all(visible > 0):
        slope, r2 = weighted_log_regression(visible, 40)
        dd = np.min(visible[-40:] / np.maximum.accumulate(visible[-40:]) - 1)
        result.update(slope40=slope, r2_40=r2, dd40=dd)
        for n in (10, 20, 40):
            result[f"return{n}"] = visible[-1] / visible[-n - 1] - 1
    return result


@dataclass
class DailyInputs:
    market: str
    day: date
    next_day: date
    month_end: bool
    features: dict
    instruments: dict
    stocks: tuple[str, ...]
    etfs: tuple[str, ...]
    breadth_codes: tuple[str, ...]
    prices: dict = field(default_factory=dict)
    trends: dict = field(default_factory=dict)
    regimes: dict = field(default_factory=dict)
    etf_regime: str | None = None
    benchmark: str = ""
    provenance: dict = field(default_factory=dict)

    def stock_eligible(self, code):
        f = self.features.get(code, {})
        return (
            f.get("valid", False)
            and finite(f.get("ma200"))
            and finite(f.get("liquidity"))
            and f["liquidity"] >= (50_000_000 if self.market == "CN" else 5_000_000)
        )

    def breadth50(self):
        eligible = [code for code in self.breadth_codes if self.stock_eligible(code)]
        if not eligible:
            raise DataNotReady("广度分母为空（需要MA200和有效流动性）")
        return sum(self.features[c]["close"] > self.features[c]["ma50"] for c in eligible) / len(eligible), len(
            eligible
        )

    def require_context(self, period):
        value = self.regimes.get(period)
        if self.etf_regime not in {"RISK_ON", "NEUTRAL", "RISK_OFF"} or not value:
            raise DataNotReady(f"等待{self.day}正式ETF与Trend{period}市场状态")
        return value


def etf_strength(features, benchmark):
    """Discovery Trend40/RS40 formula, one shared stock+ETF cross-section."""
    rows = {
        c: f
        for c, f in features.items()
        if c != benchmark and f.get("history_count", 0) >= 61 and finite(f.get("slope40"))
    }
    if not rows:
        return {}
    slopes = pd.Series({c: f["slope40"] for c, f in rows.items()})
    ranks = (slopes.rank(method="average") - 1) / (len(slopes) - 1) * 100 if len(slopes) > 1 else slopes * 0 + 100
    b = features.get(benchmark, {})
    if not all(finite(b.get(f"return{n}")) for n in (10, 20, 40)):
        return {}
    result = {}
    tq = lambda x, scale: 50 + 50 * np.tanh(x / scale)
    for code, f in rows.items():
        r2q = 100 * f["r2_40"] / (1 + np.exp(-np.clip(f["slope40"] / 0.002, -700, 700)))
        momentum = 0.6 * tq(f["return20"], 0.12) + 0.4 * tq(f["return40"], 0.18)
        trend = 0.30 * ranks[code] + 0.30 * r2q + 0.25 * momentum + 0.15 * 100 * np.exp(-abs(f["dd40"]) / 0.15)
        rs = sum(
            w * tq(f[f"return{n}"] - b[f"return{n}"], scale)
            for n, w, scale in ((10, 0.25, 0.08), (20, 0.45, 0.12), (40, 0.30, 0.18))
        )
        result[code] = dict(trend_score=float(trend), rs_score=float(rs))
    return result
