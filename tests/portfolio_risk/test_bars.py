"""Synthetic 5m bar time semantics. Not live OHLCV."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.models import Adjustment, Market, MarketBar, MinuteBarsRequest  # pragma: allowlist secret
from finance_analysis.integrations.market_data.providers.sina_minute import SinaMinuteProvider  # pragma: allowlist secret
from finance_analysis.integrations.market_data.service import _StreamingStateProvider  # pragma: allowlist secret
from finance_analysis.portfolio_risk.bars import (  # pragma: allowlist secret
    NormalizedBar,
    apply_volume_quality,
    is_complete_session_day,
    latest_expected_closed,
    normalize_market_bar,
    regular_5m_slots,
)

SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
DAY = date(2026, 9, 16)


def _bar(**kwargs):
    defaults = dict(
        symbol="600519.SH",
        market="CN",
        trade_date=DAY,
        session_id=f"{DAY.isoformat()}|AM",
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=1000,
        amount=Decimal("10500"),
        amount_quality="exact",
        volume_quality="ok",
        provider="sina_minute",
        closed=True,
        slot_key="09:35",
    )
    defaults.update(kwargs)
    return NormalizedBar(**defaults)


def test_cn_slots_exclude_lunch_and_have_48_full_day_slots():
    slots = regular_5m_slots("CN", DAY)
    ends = [item[1].astimezone(SH).strftime("%H:%M") for item in slots]
    assert ends[0] == "09:35"
    assert ends[23] == "11:30"
    assert ends[24] == "13:05"
    assert ends[-1] == "15:00"
    assert "12:00" not in ends
    assert len(slots) == 48


def test_sina_end_timestamp_maps_0935_and_1500():
    now = datetime(2026, 9, 16, 15, 10, tzinfo=SH)
    morning = MarketBar(
        symbol="600519.SH",
        market=Market.CN,
        interval="5m",
        trade_date=DAY,
        bar_time=datetime(2026, 9, 16, 9, 35, tzinfo=SH).astimezone(ZoneInfo("UTC")),
        open=10,
        high=11,
        low=9,
        close=10,
        volume=1,
        amount=10,
        currency="CNY",
        adjustment=Adjustment.RAW,
        provider="sina_minute",
        bar_start=datetime(2026, 9, 16, 9, 30, tzinfo=SH).astimezone(ZoneInfo("UTC")),
        bar_end=datetime(2026, 9, 16, 9, 35, tzinfo=SH).astimezone(ZoneInfo("UTC")),
    )
    close = replace(
        morning,
        bar_time=datetime(2026, 9, 16, 15, 0, tzinfo=SH).astimezone(ZoneInfo("UTC")),
        bar_start=datetime(2026, 9, 16, 14, 55, tzinfo=SH).astimezone(ZoneInfo("UTC")),
        bar_end=datetime(2026, 9, 16, 15, 0, tzinfo=SH).astimezone(ZoneInfo("UTC")),
    )
    n1 = normalize_market_bar(morning, now=now)
    n2 = normalize_market_bar(close, now=now)
    assert n1.bar_start.astimezone(SH).strftime("%H:%M") == "09:30"
    assert n1.bar_end.astimezone(SH).strftime("%H:%M") == "09:35"
    assert n2.bar_start.astimezone(SH).strftime("%H:%M") == "14:55"
    assert n2.bar_end.astimezone(SH).strftime("%H:%M") == "15:00"


def test_yahoo_start_timestamp_rejects_unaligned_incomplete_row():
    now = datetime(2026, 9, 16, 10, 54, tzinfo=NY)
    aligned = MarketBar(
        symbol="AAPL.US",
        market=Market.US,
        interval="5m",
        trade_date=DAY,
        bar_time=datetime(2026, 9, 16, 10, 50, tzinfo=NY).astimezone(ZoneInfo("UTC")),
        open=100,
        high=101,
        low=99,
        close=100,
        volume=10,
        amount=None,
        currency="USD",
        adjustment=Adjustment.RAW,
        provider="yfinance",
        bar_start=datetime(2026, 9, 16, 10, 50, tzinfo=NY).astimezone(ZoneInfo("UTC")),
        bar_end=datetime(2026, 9, 16, 10, 55, tzinfo=NY).astimezone(ZoneInfo("UTC")),
    )
    unaligned = replace(
        aligned,
        bar_time=datetime(2026, 9, 16, 10, 54, tzinfo=NY).astimezone(ZoneInfo("UTC")),
        bar_start=datetime(2026, 9, 16, 10, 54, tzinfo=NY).astimezone(ZoneInfo("UTC")),
        bar_end=datetime(2026, 9, 16, 10, 59, tzinfo=NY).astimezone(ZoneInfo("UTC")),
    )
    open_bar = normalize_market_bar(aligned, now=now)
    assert open_bar is not None
    assert open_bar.closed is False
    assert normalize_market_bar(unaligned, now=now) is None


def test_first_partial_day_is_not_a_complete_history_day():
    start, end, session = regular_5m_slots("CN", DAY)[-2]
    bars = [
        _bar(bar_start=start, bar_end=end, session_id=session, slot_key=end.astimezone(SH).strftime("%H:%M")),
    ]
    assert is_complete_session_day("CN", DAY, bars) is False
    full = [
        _bar(bar_start=s, bar_end=e, session_id=sid, slot_key=e.astimezone(SH).strftime("%H:%M"), trade_date=DAY)
        for s, e, sid in regular_5m_slots("CN", DAY)
    ]
    assert is_complete_session_day("CN", DAY, full) is True


def test_sina_provider_uses_stock_zh_a_minute_period_5_and_does_not_hardcode_1970():
    calls = []

    def fake(symbol):
        calls.append(symbol)
        return pd.DataFrame(
            [
                {"day": "2026-09-16 09:35:00", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000},
                {"day": "2026-09-16 15:00:00", "open": 10, "high": 11, "low": 9, "close": 10.2, "volume": 100, "amount": 1020},
            ]
        )

    provider = SinaMinuteProvider(fetch_frame=fake)
    start = datetime(2026, 9, 16, 1, tzinfo=ZoneInfo("UTC"))
    end = datetime(2026, 9, 16, 8, tzinfo=ZoneInfo("UTC"))
    result = provider.fetch_minute_bars(
        MinuteBarsRequest(("600519.SH",), start, end, interval="5m")
    )
    assert calls == ["sh600519"]
    assert len(result.data["600519.SH"]) == 2
    with pytest.raises(ValueError, match="5m"):
        provider.fetch_minute_bars(MinuteBarsRequest(("600519.SH",), start, end, interval="1m"))


def test_streaming_refuses_to_relabel_1m_as_5m():
    provider = _StreamingStateProvider(source=object())
    start = datetime(2026, 9, 16, 1, tzinfo=ZoneInfo("UTC"))
    end = datetime(2026, 9, 16, 8, tzinfo=ZoneInfo("UTC"))
    with pytest.raises(ValueError, match="1m only"):
        provider.fetch_minute_bars(MinuteBarsRequest(("600519.SH",), start, end, interval="5m"))


def test_zero_volume_quality_distinguishes_single_and_run():
    start = datetime(2026, 9, 16, 9, 30, tzinfo=SH)
    bars = []
    for index in range(4):
        bar_start = start + timedelta(minutes=5 * index)
        bars.append(
            _bar(
                bar_start=bar_start,
                bar_end=bar_start + timedelta(minutes=5),
                volume=0,
                slot_key=(bar_start + timedelta(minutes=5)).strftime("%H:%M"),
            )
        )
    marked = apply_volume_quality(bars)
    assert marked[0].volume_quality == "zero"
    assert marked[1].volume_quality == "zero"
    assert marked[2].volume_quality == "unreliable"
    assert marked[3].volume_quality == "unreliable"


def test_latest_expected_closed_uses_exchange_clock_not_fetch_time():
    now = datetime(2026, 9, 16, 9, 37, tzinfo=SH)
    expected = latest_expected_closed("CN", now)
    assert expected.astimezone(SH).strftime("%H:%M") == "09:35"
