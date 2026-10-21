"""Build explicitly approximate minute bars from cumulative quote snapshots."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.market_stream.session import in_session


class MinuteSampler:
    def __init__(self):
        self.current = {}
        self.previous = {}

    def remove(self, symbol):
        self.current.pop(symbol, None)
        self.previous.pop(symbol, None)

    def advance(self, now):
        completed = []
        for symbol, bar in list(self.current.items()):
            if now >= bar.bar_time + timedelta(minutes=1):
                completed.append(
                    replace(
                        bar,
                        confirmed=True,
                        partial=(bar.partial or bar.sample_count < 3 or bar.bar_time + timedelta(minutes=1) - bar.received_at > timedelta(seconds=30)),
                    )
                )
                self.current.pop(symbol)
        return completed

    def observe(self, quote, now):
        """Missing or stale provider timestamps never become fresh observation bars."""
        at = quote.quote_time
        if (
            at is None
            or not -5 <= (now - at).total_seconds() <= 30
            or not in_session("CN", at)
            or not in_session("CN", now)
            or quote.price is None
            or quote.price <= 0
        ):
            return None
        symbol = quote.symbol
        previous = self.previous.get(symbol)
        if previous is not None and at <= previous.quote_time:
            return None
        minute = at.replace(second=0, microsecond=0)
        if minute != now.replace(second=0, microsecond=0):
            return None
        old = self.current.get(symbol)
        same_minute = old is not None and old.bar_time == minute
        continuous = previous is not None and timedelta(0) < at - previous.quote_time <= timedelta(seconds=30)
        same_session = continuous and at.astimezone(ZoneInfo("Asia/Shanghai")).hour // 12 == (
            previous.quote_time.astimezone(ZoneInfo("Asia/Shanghai")).hour // 12
        )
        valid_volume = same_session and quote.volume is not None and previous.volume is not None
        delta = quote.volume - previous.volume if valid_volume else 0
        reset = delta < 0
        turnover = None
        if (
            same_session
            and quote.amount is not None
            and previous.amount is not None
            and quote.amount >= previous.amount
        ):
            turnover = Decimal(str(quote.amount)) - Decimal(str(previous.amount))
        price = Decimal(str(quote.price))
        if same_minute:
            bar = replace(
                old,
                high=max(old.high, price),
                low=min(old.low, price),
                close=price,
                volume=old.volume + max(0, delta),
                turnover=old.turnover + turnover if old.turnover is not None and turnover is not None else None,
                sample_count=old.sample_count + 1,
                received_at=now,
                partial=old.partial or not continuous or not valid_volume or reset,
            )
        else:
            bar = CandleState(
                symbol,
                minute,
                price,
                price,
                price,
                price,
                max(0, delta),
                turnover,
                "Intraday",
                False,
                now,
                source="fuyao",
                sampled=True,
                sample_count=1,
                partial=not same_session or not valid_volume or reset or at.second > 15,
            )
        self.previous[symbol] = quote
        self.current[symbol] = bar
        return bar
