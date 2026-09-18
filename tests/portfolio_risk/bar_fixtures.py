"""Synthetic regular-session 5m bars across real trading dates. Not live OHLCV."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.market_review.trading_calendar import is_market_open  # pragma: allowlist secret
from finance_analysis.portfolio_risk.bars import NormalizedBar, regular_5m_slots  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")


def trading_dates(market: str, last: date, *, count: int) -> list[date]:
    dates: list[date] = []
    cursor = last
    while len(dates) < count:
        if is_market_open(market.lower(), cursor):
            dates.append(cursor)
        cursor = cursor - timedelta(days=1)
        if cursor.year < last.year - 1:
            break
    return list(reversed(dates))


def session_bars(
    *,
    symbol: str = "600519.SH",
    market: str = "CN",
    days: list[date],
    close: Decimal = Decimal("100"),
    until: datetime | None = None,
    high_close: Decimal | None = None,
    high_on: date | None = None,
    volume: int = 2000,
    provider: str = "sina_minute",
) -> list[NormalizedBar]:
    """Build closed regular-session bars. Future slots relative to `until` are omitted."""

    zone = ZoneInfo("Asia/Shanghai") if market == "CN" else ZoneInfo("America/New_York")
    bars: list[NormalizedBar] = []
    for trade_date in days:
        for start, end, session in regular_5m_slots(market, trade_date):
            if until is not None and end > until:
                continue
            bar_close = close
            if high_close is not None and (high_on is None or trade_date == high_on):
                if end.astimezone(zone).hour == 10 and end.astimezone(zone).minute == 0:
                    bar_close = high_close
            bars.append(
                NormalizedBar(
                    symbol=symbol,
                    market=market,
                    trade_date=trade_date,
                    bar_start=start,
                    bar_end=end,
                    session_id=session,
                    open=bar_close,
                    high=bar_close + Decimal("1"),
                    low=bar_close - Decimal("1"),
                    close=bar_close,
                    volume=volume,
                    amount=bar_close * volume,
                    amount_quality="exact",
                    volume_quality="ok",
                    provider=provider,
                    closed=True,
                    slot_key=end.astimezone(zone).strftime("%H:%M"),
                )
            )
    return bars


def recover_last_adjacent(bars: list[NormalizedBar], *, count: int = 2, close: Decimal = Decimal("108")) -> list[NormalizedBar]:
    updated = list(bars)
    for index in range(count, 0, -1):
        bar = updated[-index]
        updated[-index] = replace(
            bar,
            open=close - Decimal("1"),
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            amount=close * bar.volume,
        )
    return updated


def weaken_last_adjacent(bars: list[NormalizedBar], *, count: int = 2, close: Decimal = Decimal("90")) -> list[NormalizedBar]:
    updated = list(bars)
    for index in range(count, 0, -1):
        bar = updated[-index]
        bar_close = close - Decimal(2 * (count - index))
        updated[-index] = replace(
            bar,
            open=bar_close + Decimal("10"),
            high=bar_close + Decimal("10"),
            low=bar_close - Decimal("1"),
            close=bar_close,
            amount=bar_close * bar.volume,
        )
    return updated
