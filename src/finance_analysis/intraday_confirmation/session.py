"""Exchange sessions, including lunch, holidays, DST and US early closes."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from finance_analysis.market_review import trading_calendar as calendar


@dataclass(frozen=True)
class Session:
    market: str
    opened: datetime
    closed: datetime
    previous_date: date

    @property
    def day(self):
        return self.opened.date()

    def intervals(self):
        if self.market == "CN":
            return [
                (self.opened, self.opened.replace(hour=11, minute=30)),
                (self.opened.replace(hour=13, minute=0), self.closed),
            ]
        return [(self.opened, self.closed)]

    def elapsed(self, stamp):
        return sum(max(0, (min(stamp, end) - start).total_seconds() / 60) for start, end in self.intervals())

    def active(self, stamp):
        return any(start <= stamp <= end for start, end in self.intervals())

    def slots(self, until, minutes=5):
        slots = []
        for start, end in self.intervals():
            while start + timedelta(minutes=minutes) <= min(end, until):
                slots.append(start)
                start += timedelta(minutes=minutes)
        return slots


def resolve_session(market, now):
    # Candidate date must be an actual preceding exchange session, never weekday fallback.
    if not calendar._XCALS_AVAILABLE:
        raise RuntimeError("交易日历不可用，不能冻结候选")
    local = now.astimezone(ZoneInfo(calendar.MARKET_TIMEZONE[market.lower()]))
    days = calendar.get_trading_days_between(market.lower(), local.date() - timedelta(days=30), local.date())
    if not days or days[-1] != local.date():
        return None
    opened, closed = calendar.get_market_session_bounds(market.lower(), local.date())
    # XSHG versions without a lunch break still have the correct session close.
    return Session(market, opened, closed, days[-2])


def expires_at(session):
    return datetime.combine(session.day + timedelta(days=1), time.min, session.opened.tzinfo)
