"""Read-only close-to-close research returns on exact exchange sessions."""

from datetime import date
from math import isfinite

from finance_analysis.core.time import utc_now
from finance_analysis.market_review import trading_calendar as calendar

HORIZONS = (3, 5, 10)


def forward_returns(service, symbols: list[str], market: str, trade_date: date, *, now=None) -> dict:
    now = now or utc_now()
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("交易日历暂时不可用")
    cal = calendar.xcals.get_calendar(calendar.MARKET_EXCHANGE[market.lower()])
    session = cal.date_to_session(trade_date, direction="none")
    targets = {}
    for step in range(1, 11):
        session = cal.next_session(session)
        if step in HORIZONS:
            targets[step] = (session.date(), cal.session_close(session).to_pydatetime())
    matured = [day for day, close in targets.values() if close <= now]
    data = {}
    if matured:
        data = service.get_daily_bars(
            symbols, trade_date, max(matured), adjustment="forward", source_policy="db_only"
        ).data
    items = []
    for code in symbols:
        bars = {bar.trade_date: bar for bar in data.get(code, [])}
        base = bars.get(trade_date)
        values = {}
        for horizon, (day, close) in targets.items():
            target = bars.get(day)
            valid = close <= now and all(
                bar is not None and isfinite(bar.close) and bar.close > 0 and bar.volume > 0
                for bar in (base, target)
            )
            values[f"forward_return_{horizon}d"] = target.close / base.close - 1 if valid else None
        items.append({"code": code, **values})
    return {"trade_date": trade_date, "items": items}
