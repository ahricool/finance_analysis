"""Read-only close-to-close research returns on exact exchange sessions."""

from datetime import date
from math import isfinite

from finance_analysis.core.time import utc_now
from .research import following_sessions

HORIZONS = (3, 5, 10, 20)


def forward_returns(service, symbols: list[str], market: str, trade_date: date, *, now=None) -> dict:
    now = now or utc_now()
    plan = following_sessions(market, trade_date, max(HORIZONS))
    targets = {step: plan[step - 1] for step in HORIZONS}
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
