"""Read-only display valuation; execution freshness rules remain in Trade Engine."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.core.time import coerce_aware_utc, utc_isoformat, utc_now
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.portfolio.service import PortfolioService
from finance_analysis.portfolio.views import _account_payload, _json_dec, _position_payload


def position_valuation(item, quote, operations, *, now):
    price = Decimal(str(quote.price)) if quote is not None and quote.price is not None else None
    as_of = quote.quote_time if quote is not None else None
    if price is None or price <= 0 or as_of is None or as_of > now + timedelta(seconds=30):
        price = None
    previous = Decimal(str(quote.pre_close)) if quote is not None and quote.pre_close else None
    change = price - previous if price is not None and previous is not None and previous > 0 else None
    cost, qty = item["average_cost"], item["quantity"]
    pnl = (price - cost) * qty if price is not None else None
    day_pnl = None
    if change is not None:
        day_pnl = change * qty
        quote_day = market_trading_date(as_of, item["market"])
        for op in operations:
            when = coerce_aware_utc(op["executed_at"])
            if when <= now and market_trading_date(when, item["market"]) == quote_day:
                adjustment = op["quantity"] * (op["price"] - previous)
                day_pnl += adjustment if op["side"] == "SELL" else -adjustment
    return {
        "current_price": _json_dec(price),
        "market_value": _json_dec(price * qty if price is not None else None),
        "unrealized_pnl": _json_dec(pnl),
        "unrealized_pnl_pct": _json_dec((price / cost - 1) * 100 if price is not None and cost > 0 else None),
        "change_amount": _json_dec(change),
        "change_pct": _json_dec(change / previous * 100 if change is not None else None),
        "day_pnl": _json_dec(day_pnl),
        "quote_time": utc_isoformat(as_of) if as_of is not None else None,
        "quote_source": quote.provider if quote is not None else None,
        "quote_status": (
            "unavailable" if price is None else "delayed" if now - as_of > timedelta(seconds=90) else "current"
        ),
    }


def portfolio_summary(uid: int, market: str, *, service=None, market_data=None, initialize_accounts=True):
    service = service or PortfolioService()
    if initialize_accounts:
        service.ensure_accounts(uid)
    accounts, positions = service.read_snapshot(uid, market)
    snapshot_at = utc_now()
    symbols = list(dict.fromkeys(item["symbol"] for item in positions))
    names = InstrumentRepository(service.repository.db).names_by_codes(symbols) if symbols else {}
    quotes = {}
    if symbols:
        try:
            quotes = (market_data or MarketDataService()).get_realtime_quotes(symbols).data
        except Exception:
            # An unavailable feed must not prevent access to owned positions or cash.
            quotes = {}
    now = utc_now()
    quote_dates = [market_trading_date(q.quote_time, market) for q in quotes.values() if q.quote_time]
    zone = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
    start = datetime.combine(min(quote_dates or [now.astimezone(zone).date()]), time.min, zone)
    operations = service.operations_in_window(uid, [item["id"] for item in positions], start, snapshot_at)
    by_position = {}
    for op in operations:
        by_position.setdefault(op["position_id"], []).append(op)
    priced = [
        {
            **_position_payload(item),
            "name": names.get(item["symbol"]),
            **position_valuation(item, quotes.get(item["symbol"]), by_position.get(item["id"], []), now=now),
        }
        for item in positions
    ]
    cash = sum((item["cash"] for item in accounts), Decimal("0"))
    value = sum((Decimal(item["market_value"]) for item in priced if item["market_value"] is not None), Decimal("0"))
    total = cash + value
    for item in priced:
        item["weight"] = (
            _json_dec(Decimal(item["market_value"]) / total) if total > 0 and item["market_value"] is not None else None
        )
    return {
        "market": market,
        "accounts": [_account_payload(item) for item in accounts],
        "cash": _json_dec(cash),
        "market_value": _json_dec(value),
        "total_asset": _json_dec(total),
        "gross_exposure": _json_dec(value / total) if total > 0 else None,
        "positions": priced,
        "missing_quote_count": sum(item["current_price"] is None for item in priced),
        # Order account/position facts by read time, not by when a slow quote request finishes.
        "generated_at": utc_isoformat(snapshot_at),
    }
