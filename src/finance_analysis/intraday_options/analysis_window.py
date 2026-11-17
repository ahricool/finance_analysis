"""Local analysis-only flat bars; never persist them as observed market candles."""

from dataclasses import replace
from datetime import timedelta

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds

MINUTE = timedelta(minutes=1)
HORIZON = 60
REQUIRED_MINUTES = 15
FLAT_SOURCE = "intraday_flat_fill"


def analysis_window(ordered):
    end = ordered[-1].bar_time
    opening, _ = session_bounds("US", market_trading_date(end, "US"))
    start = max(opening, end - (HORIZON - 1) * MINUTE)
    raw = {b.bar_time: b for b in ordered if start <= b.bar_time <= end}
    valid = {t: b for t, b in raw.items() if b.is_valid() and not b.partial and not b.sampled}
    bars, filled = [], []
    previous = None
    last_valid = max(valid, default=start - MINUTE)
    at = start
    while at <= end:
        bar = valid.get(at)
        if bar is not None:
            previous = bar
            bars.append(bar)
        elif at not in raw and previous is not None and at < last_valid:
            # Previous close only: never interpolate from the next observed price.
            # Zero is a placeholder, not evidence of zero trading volume.
            bars.append(replace(previous, bar_time=at, open=previous.close, high=previous.close,
                                low=previous.close, close=previous.close, volume=0, turnover=None,
                                source=FLAT_SOURCE, sample_count=0))
            filled.append(at.isoformat())
        else:
            # Explicit invalid/partial/sampled bars are not silently repaired.
            previous = None
        at += MINUTE
    recent_start = end - (REQUIRED_MINUTES - 1) * MINUTE
    recent = [b for b in bars if b.bar_time >= recent_start]
    warming = end + MINUTE - opening < REQUIRED_MINUTES * MINUTE
    coverage = {
        "required_minutes": REQUIRED_MINUTES,
        "recent_available_bars": len(recent),
        "recent_missing_bars": REQUIRED_MINUTES - len(recent),
        "missing_bars": int((end - start) / MINUTE) + 1 - len(bars),
        "filled_bars": len(filled),
        "filled_minutes": filled,
        "reference": warming or len(recent) < REQUIRED_MINUTES,
    }
    reasons = [f"最近{REQUIRED_MINUTES}根闭合分钟K完整后开始判断，最多参考{HORIZON}分钟背景"]
    if coverage["reference"]:
        reasons.append(f"最近{REQUIRED_MINUTES}分钟尚缺{REQUIRED_MINUTES - len(recent)}根可用K，等待完整窗口")
    if filled:
        reasons.append(f"背景中{len(filled)}根空缺分钟按前收盘补为平K；成交量未知，不用补线独立确认进场")
    if coverage["missing_bars"]:
        reasons.append(f"背景仍缺{coverage['missing_bars']}根有效K；15分钟以外缺口不单独阻断判断")
    return bars, coverage, reasons


def observed(bar):
    return bar.source != FLAT_SOURCE
