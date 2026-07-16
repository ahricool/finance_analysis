from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.market_stream.trend import calculate_ma_trend


def candle(
    when: datetime,
    close: int | str,
    *,
    symbol: str = "AAPL.US",
    confirmed: bool = True,
    session: str = "Intraday",
    received_offset: int = 61,
) -> CandleState:
    price = Decimal(str(close))
    return CandleState(
        symbol=symbol,
        bar_time=when,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=100,
        turnover=price * 100,
        trade_session=session,
        confirmed=confirmed,
        received_at=when + timedelta(seconds=received_offset),
    )


US_OPEN = datetime(2026, 7, 16, 13, 30, tzinfo=timezone.utc)


def trend_for(closes: list[int | str], *, extra: list[CandleState] | None = None):
    bars = [candle(US_OPEN + timedelta(minutes=index), close) for index, close in enumerate(closes)]
    return calculate_ma_trend(
        [*bars, *(extra or [])],
        market_type="US",
        as_of=US_OPEN + timedelta(minutes=max(len(closes), 1) + 1),
    )


@pytest.mark.parametrize("count", [0, 1, 4])
def test_insufficient_valid_bars(count: int) -> None:
    trend = trend_for(list(range(1, count + 1)))
    assert trend.state == "insufficient"
    assert trend.effective_period == count
    assert trend.streak == 0
    assert trend.ma_value is None
    assert not trend.confirmed


@pytest.mark.parametrize("count", [5, 19, 20])
def test_dynamic_effective_period_and_mean(count: int) -> None:
    trend = trend_for(list(range(1, count + 1)))
    assert trend.effective_period == count
    assert trend.ma_value == Decimal(count + 1) / Decimal("2")
    assert trend.state == "above"


def test_twenty_first_bar_uses_only_bars_two_through_twenty_one() -> None:
    trend = trend_for(list(range(1, 22)))
    assert trend.effective_period == 20
    assert trend.ma_value == Decimal("11.5")


def test_each_bar_uses_its_own_rolling_mean_for_streak() -> None:
    trend = trend_for([1, 2, 3, 4, 5, 6, 7])
    assert trend.state == "above"
    assert trend.streak == 3


@pytest.mark.parametrize(
    ("closes", "state", "streak"),
    [
        ([7, 6, 5, 4, 3, 2, 1], "below", 3),
        ([1, 2, 3, 4, 5, 6, 1], "below", 1),
        ([7, 6, 5, 4, 3, 2, "4.5"], "neutral", 1),
        ([5, 5, 5, 5, 5, 5, 5], "neutral", 3),
    ],
)
def test_streak_direction_changes(closes, state: str, streak: int) -> None:
    trend = trend_for(closes)
    assert trend.state == state
    assert trend.streak == streak


def test_unconfirmed_invalid_extended_previous_day_and_future_bars_are_ignored() -> None:
    bars = [candle(US_OPEN + timedelta(minutes=index), index + 1) for index in range(5)]
    unconfirmed = candle(US_OPEN + timedelta(minutes=5), 100, confirmed=False)
    invalid = candle(US_OPEN + timedelta(minutes=6), 100)
    invalid.high = Decimal("1")
    premarket = candle(US_OPEN - timedelta(minutes=1), 100, session="Pre")
    postmarket = candle(US_OPEN + timedelta(hours=7), 100, session="Post")
    previous = candle(US_OPEN - timedelta(days=1), 100)
    trend = calculate_ma_trend(
        [postmarket, invalid, *reversed(bars), previous, unconfirmed, premarket],
        market_type="US",
        as_of=US_OPEN + timedelta(minutes=8),
    )
    assert trend.close == Decimal("5")
    assert trend.effective_period == 5


def test_duplicate_and_out_of_order_bars_do_not_increase_streak() -> None:
    bars = [candle(US_OPEN + timedelta(minutes=index), index + 1) for index in range(7)]
    duplicate = candle(US_OPEN + timedelta(minutes=6), 7, received_offset=120)
    trend = calculate_ma_trend(
        [duplicate, *reversed(bars)],
        market_type="US",
        as_of=US_OPEN + timedelta(minutes=8),
    )
    assert trend.streak == 3
    assert trend.effective_period == 7


@pytest.mark.parametrize(
    ("market", "start", "symbol"),
    [
        ("CN", datetime(2026, 7, 16, 1, 30, tzinfo=timezone.utc), "600519.SH"),
        ("HK", datetime(2026, 7, 16, 1, 30, tzinfo=timezone.utc), "0700.HK"),
        ("US", US_OPEN, "AAPL.US"),
    ],
)
def test_market_timezones_and_regular_sessions(market, start: datetime, symbol: str) -> None:
    bars = [candle(start + timedelta(minutes=index), index + 1, symbol=symbol) for index in range(5)]
    trend = calculate_ma_trend(bars, market_type=market, as_of=start + timedelta(minutes=6))
    assert trend.state == "above"
    assert trend.trading_date.isoformat() == "2026-07-16"


@pytest.mark.parametrize(
    ("market", "morning", "afternoon", "symbol"),
    [
        (
            "CN",
            datetime(2026, 7, 16, 3, 27, tzinfo=timezone.utc),
            datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc),
            "600519.SH",
        ),
        (
            "HK",
            datetime(2026, 7, 16, 3, 57, tzinfo=timezone.utc),
            datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc),
            "0700.HK",
        ),
    ],
)
def test_lunch_recess_does_not_reset_streak(market, morning, afternoon, symbol: str) -> None:
    times = [morning + timedelta(minutes=index) for index in range(3)] + [
        afternoon + timedelta(minutes=index) for index in range(3)
    ]
    bars = [candle(when, index + 1, symbol=symbol) for index, when in enumerate(times)]
    trend = calculate_ma_trend(bars, market_type=market, as_of=afternoon + timedelta(minutes=4))
    assert trend.state == "above"
    assert trend.streak == 2


def test_cross_trading_date_resets_and_distance_uses_decimal() -> None:
    previous = [candle(US_OPEN - timedelta(days=1) + timedelta(minutes=index), 100) for index in range(20)]
    current = [candle(US_OPEN + timedelta(minutes=index), close) for index, close in enumerate([1, 2, 3, 4, 5])]
    trend = calculate_ma_trend([*previous, *current], market_type="US", as_of=US_OPEN + timedelta(minutes=6))
    assert trend.effective_period == 5
    assert trend.streak == 1
    assert trend.distance_pct == (Decimal("5") / Decimal("3") - 1) * 100
