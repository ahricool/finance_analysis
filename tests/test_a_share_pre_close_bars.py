# -*- coding: utf-8 -*-
"""Pre-close minute bar normalization (moved from deleted A-share intraday job)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.bars import (  # pragma: allowlist secret
    aggregate_bars,
    normalize_bars,
)

SH = ZoneInfo("Asia/Shanghai")


def _bar(ts: datetime, open_price: float, close: float, volume: int = 1000) -> dict:
    high = max(open_price, close) + 0.05
    low = min(open_price, close) - 0.05
    return {
        "timestamp": ts.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover": close * volume,
    }


def test_normalize_bars_filters_lunch_and_future_and_dedupes():
    base = datetime(2026, 6, 24, 10, 0, tzinfo=SH)
    now = datetime(2026, 6, 24, 11, 0, tzinfo=SH)
    raw = [
        _bar(base, 10.0, 10.1),
        _bar(base, 10.0, 10.1),
        _bar(datetime(2026, 6, 24, 12, 15, tzinfo=SH), 10.0, 10.2),
        _bar(datetime(2026, 6, 24, 14, 0, tzinfo=SH), 10.0, 10.3),
        _bar(datetime(2026, 6, 24, 10, 30, tzinfo=SH), 10.1, 10.2),
    ]
    bars = normalize_bars(raw, now=now)
    times = [item["timestamp"] for item in bars]
    assert len(bars) == 2
    assert times == sorted(times)


def test_normalize_bars_excludes_still_forming_current_minute():
    now = datetime(2026, 6, 24, 11, 30, tzinfo=SH)
    bars = normalize_bars(
        [
            _bar(datetime(2026, 6, 24, 11, 29, tzinfo=SH), 10.0, 10.1),
            _bar(datetime(2026, 6, 24, 11, 30, tzinfo=SH), 10.1, 10.2),
        ],
        now=now,
    )
    assert [bar["timestamp"] for bar in bars] == ["2026-06-24T11:29:00+08:00"]


def test_aggregate_bars_builds_5m_ohlcv():
    start = datetime(2026, 6, 24, 10, 0, tzinfo=SH)
    bars = [_bar(start + timedelta(minutes=i), 10 + i * 0.1, 10.05 + i * 0.1, volume=100 + i) for i in range(6)]
    result = aggregate_bars(bars, 5)
    assert len(result) == 2
