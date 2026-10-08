"""Yahoo daily chains and Alpaca snapshots/contracts, using existing HTTP infrastructure."""

import math
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from finance_analysis.core.retry import retry_call, transient_response
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider
from finance_analysis.integrations.market_data.providers.alpaca import AlpacaHTTPError
from .models import OptionChain, OptionObservation


def number(value, *, signed=False):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) and (signed or parsed >= 0) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, (int, float)):
            result = datetime.fromtimestamp(value, timezone.utc)
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def occ(symbol):
    match = re.fullmatch(r"([A-Z0-9.]+)(\d{6})([CP])(\d{8})", symbol)
    if not match:
        raise ValueError("Invalid OCC option symbol")
    root, expiry, kind, strike = match.groups()
    return root, datetime.strptime(expiry, "%y%m%d").date(), "call" if kind == "C" else "put", int(strike) / 1000


def expiry_priority(expirations, session_date):
    """Protect the 30D bracket, then 7D/60D, before extra nearby expirations."""
    days = sorted(set(expirations))
    anchors = []
    for candidates in (
        [d for d in days if (d - session_date).days <= 30],
        [d for d in days if (d - session_date).days >= 30],
    ):
        if candidates:
            anchors.append(min(candidates, key=lambda d: abs((d - session_date).days - 30)))
    for target in (7, 30, 60):
        if days:
            anchors.append(min(days, key=lambda d: abs((d - session_date).days - target)))
    return list(dict.fromkeys(anchors + days))


def select_contracts(rows, session_date, config):
    """Bound one source/feed, allocating expiry budgets and alternating Call/Put.

    Each side starts with ATM and then a representative OTM (25Δ when supplied).
    Unknown spot never uses an absolute-strike prefix as a supposedly valid chain.
    """
    unique = {r.symbol: r for r in rows}
    eligible = [
        r
        for r in unique.values()
        if 0 < (r.expiration - session_date).days <= config.max_dte
        and r.strike > 0
        and r.multiplier in {None, 100}
        and not any(c.isdigit() for c in occ(r.symbol)[0])
    ]
    priced = all(number(r.underlying_price) and r.underlying_price > 0 for r in eligible)
    if priced:
        eligible = [
            r for r in eligible if config.min_moneyness <= r.strike / r.underlying_price <= config.max_moneyness
        ]
    by_expiry = defaultdict(list)
    for row in eligible:
        by_expiry[row.expiration].append(row)
    priority = expiry_priority(by_expiry, session_date)[: config.max_expirations]
    # Reserve a Call/Put pair per retained expiry when possible.
    if len(eligible) > config.max_contracts:
        priority = priority[: max(1, config.max_contracts // 2)]
    queues = {}
    for expiry in priority:
        sides = []
        common = {r.strike for r in by_expiry[expiry] if r.option_type == "call"} & {
            r.strike for r in by_expiry[expiry] if r.option_type == "put"
        }
        spot = by_expiry[expiry][0].underlying_price
        atm_strike = min(common, key=lambda strike: (abs(strike / spot - 1), strike)) if priced and common else None
        for kind in ("call", "put"):
            side = [r for r in by_expiry[expiry] if r.option_type == kind]
            if priced:
                side.sort(
                    key=lambda r: (
                        r.strike != atm_strike if atm_strike is not None else False,
                        abs(r.strike / r.underlying_price - 1),
                        r.symbol,
                    )
                )
                otm = [
                    r
                    for r in side
                    if (r.strike > r.underlying_price if kind == "call" else r.strike < r.underlying_price)
                ]
                delta_otm = [
                    r
                    for r in otm
                    if r.delta is not None and (0 < r.delta <= 1 if kind == "call" else -1 <= r.delta < 0)
                ]
                representative = (
                    min(delta_otm, key=lambda r: abs(abs(r.delta) - 0.25))
                    if delta_otm
                    else otm[len(otm) // 2] if otm else None
                )
                if side and representative and representative is not side[0]:
                    side = [side[0], representative] + [r for r in side[1:] if r is not representative]
            sides.append(side)
        queues[expiry] = [
            row for i in range(max(map(len, sides), default=0)) for side in sides if i < len(side) for row in [side[i]]
        ]
    retained = []
    if not priced and len(eligible) > config.max_contracts:
        status = "underlying_missing_selection_unavailable"
    else:
        # Round-robin gives small expiry chains their full allocation without wasting budget.
        while len(retained) < config.max_contracts and any(queues.values()):
            for expiry in priority:
                if queues[expiry] and len(retained) < config.max_contracts:
                    retained.append(queues[expiry].pop(0))
        status = (
            "complete" if priced and len(retained) == len(eligible) else "limited" if priced else "underlying_missing"
        )
    counts = {}
    for expiry, contracts in sorted(by_expiry.items()):
        kept = [r for r in retained if r.expiration == expiry]
        counts[expiry.isoformat()] = {
            "available": {kind: sum(r.option_type == kind for r in contracts) for kind in ("call", "put")},
            "retained": {kind: sum(r.option_type == kind for r in kept) for kind in ("call", "put")},
        }
    return retained, {
        "eligible_contract_count": len(eligible),
        "retained_contract_count": len(retained),
        "covered_expirations": sorted({r.expiration.isoformat() for r in retained}),
        "expiration_counts": counts,
        "truncated_contracts": len(retained) < len(eligible),
        "selection_status": status,
        "moneyness_filter_applied": priced,
    }


def yahoo_observation(row, symbol, expiration, kind, now, session_date, underlying):
    # Yahoo exposes lastTradeDate, not a bid/ask timestamp or an OI as-of date.
    multiplier = 100.0 if row.get("contractSize") == "REGULAR" else None
    last_trade = timestamp(row.get("lastTradeDate"))
    volume_date = (
        session_date
        if last_trade and last_trade.astimezone(ZoneInfo("America/New_York")).date() == session_date
        else None
    )
    return OptionObservation(
        symbol=str(row["contractSymbol"]),
        underlying_symbol=symbol,
        expiration=expiration,
        option_type=kind,
        strike=float(row["strike"]),
        multiplier=multiplier,
        bid=number(row.get("bid")),
        ask=number(row.get("ask")),
        volume=number(row.get("volume")),
        volume_date=volume_date,
        open_interest=number(row.get("openInterest")),
        last_price=number(row.get("lastPrice")),
        last_trade_time=last_trade,
        iv=number(row.get("impliedVolatility")),
        underlying_price=number(underlying.get("regularMarketPrice")),
        underlying_timestamp=timestamp(underlying.get("regularMarketTime")),
        observed_at=now,
        data_source="yfinance",
        feed_type="delayed",
        limitations=["quote_timestamp_unknown", "oi_as_of_unknown", "volume_session_inferred", "iv_timestamp_unknown"],
    )


class YahooOptionsProvider:
    def __init__(self, ticker_factory=None):
        self.ticker_factory = ticker_factory

    def fetch(self, symbol, now, session_date, config):
        import yfinance as yf

        ticker = (self.ticker_factory or yf.Ticker)(YFinanceProvider.to_yfinance_symbol(symbol))
        expirations = [date.fromisoformat(value) for value in retry_call(lambda: ticker.options)]
        expirations = [day for day in expirations if 0 < (day - session_date).days <= config.max_dte]
        result = OptionChain(symbol=symbol, observed_at=now)
        selected = sorted(expiry_priority(expirations, session_date)[: config.max_expirations])
        for expiration in selected:
            try:
                chain = retry_call(lambda: ticker.option_chain(expiration.isoformat()))
                underlying = chain.underlying or {}
                for kind, frame in (("call", chain.calls), ("put", chain.puts)):
                    for row in frame.to_dict("records"):
                        observation = yahoo_observation(row, symbol, expiration, kind, now, session_date, underlying)
                        spot = observation.underlying_price
                        if not spot or config.min_moneyness <= observation.strike / spot <= config.max_moneyness:
                            result.observations.append(observation)
            except Exception as exc:
                result.errors.append(f"yfinance:{expiration}:{type(exc).__name__}")
        result.coverage = {
            "available_expirations": [d.isoformat() for d in expirations],
            "selected_expirations": [d.isoformat() for d in selected],
            "truncated_expirations": len(expirations) > len(selected),
        }
        if all(number(r.underlying_price) for r in result.observations):
            result.observations, coverage = select_contracts(result.observations, session_date, config)
            result.coverage.update(coverage)
        else:
            result.coverage["selection_status"] = "deferred_missing_underlying"
        return result


def alpaca_observation(symbol, underlying, row, contract, now, feed):
    _, expiration, kind, strike = occ(symbol)
    quote, trade, greeks = row.get("latestQuote") or {}, row.get("latestTrade") or {}, row.get("greeks") or {}
    oi_date = contract.get("open_interest_date")
    daily = row.get("dailyBar") or {}
    bar_time = timestamp(daily.get("t"))
    volume_date = bar_time.astimezone(ZoneInfo("America/New_York")).date() if bar_time else None
    return OptionObservation(
        symbol=symbol,
        underlying_symbol=underlying,
        expiration=expiration,
        option_type=kind,
        strike=strike,
        multiplier=number(contract.get("multiplier")) or number(contract.get("size")),
        bid=number(quote.get("bp")),
        ask=number(quote.get("ap")),
        bid_size=number(quote.get("bs")),
        ask_size=number(quote.get("as")),
        quote_timestamp=timestamp(quote.get("t")),
        last_price=number(trade.get("p")),
        last_trade_time=timestamp(trade.get("t")),
        open_interest=number(contract.get("open_interest")),
        oi_date=date.fromisoformat(oi_date) if oi_date else None,
        volume=number(daily.get("v")) if bar_time else None,
        volume_date=volume_date,
        traded_price=number(daily.get("vw")) if bar_time and feed == "opra" else None,
        traded_price_method="reported_daily_vwap" if bar_time and feed == "opra" else None,
        iv=number(row.get("impliedVolatility")),
        delta=number(greeks.get("delta"), signed=True),
        gamma=number(greeks.get("gamma"), signed=True),
        theta=number(greeks.get("theta"), signed=True),
        vega=number(greeks.get("vega"), signed=True),
        observed_at=now,
        data_source="alpaca",
        feed_type=feed,
        # Snapshot API does not document an IV/Greeks timestamp or daily volume.
        limitations=["iv_timestamp_unknown"]
        + (["daily_volume_unavailable"] if not bar_time else [])
        + (["indicative_modified_quotes_delayed_trades"] if feed == "indicative" else [])
        + (["greeks_unavailable"] if not greeks else [])
        + (["iv_unavailable"] if row.get("impliedVolatility") is None else []),
    )


class AlpacaOptionsProvider:
    def __init__(self, *, key=None, secret=None, transport=None):
        self.key = key if key is not None else os.getenv("ALPACA_API_KEY", "")
        self.secret = secret if secret is not None else os.getenv("ALPACA_SECRET_KEY", "")
        self.transport = transport

    @staticmethod
    def _pages(client, url, params, field, max_rows):
        output = {} if field == "snapshots" else []
        seen = set()
        for _ in range(50):
            response = retry_call(lambda: client.get(url, params=params), retry_result=transient_response)
            if response.status_code != 200:
                raise AlpacaHTTPError(response)
            body = response.json()
            data = body.get(field)
            if isinstance(output, dict) and isinstance(data, dict):
                output.update(data)
            elif isinstance(output, list) and isinstance(data, list):
                output.extend(data)
            else:
                raise ValueError("Invalid Alpaca options payload")
            token = body.get("next_page_token")
            if not token:
                return output
            if token in seen or len(output) >= max_rows:
                raise ValueError("Alpaca options pagination incomplete")
            seen.add(token)
            params = {**params, "page_token": token}
        raise ValueError("Alpaca options pagination limit exceeded")

    def fetch(self, symbol, now, session_date, config, underlying_price=None):
        result = OptionChain(symbol=symbol, observed_at=now)
        if not self.key or not self.secret:
            result.errors.append("alpaca:credentials_not_configured")
            return result
        bare = symbol.removesuffix(".US")
        bounds = {
            "expiration_date_gte": (session_date + timedelta(days=1)).isoformat(),
            "expiration_date_lte": (session_date + timedelta(days=config.max_dte)).isoformat(),
        }
        if underlying_price:
            bounds.update(
                {
                    "strike_price_gte": underlying_price * config.min_moneyness,
                    "strike_price_lte": underlying_price * config.max_moneyness,
                }
            )
        with httpx.Client(
            headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret},
            timeout=20,
            transport=self.transport,
        ) as client:
            contracts = {}
            try:
                base = os.getenv("ALPACA_OPTIONS_CONTRACTS_URL", "https://paper-api.alpaca.markets")
                rows = self._pages(
                    client,
                    base.rstrip("/") + "/v2/options/contracts",
                    {**bounds, "underlying_symbols": bare, "limit": 1000},
                    "option_contracts",
                    config.max_contracts * 4,
                )
                contracts = {row["symbol"]: row for row in rows}
            except (httpx.HTTPError, ValueError) as exc:
                result.errors.append(
                    f"alpaca:contracts:{str(exc) if isinstance(exc, ValueError) else type(exc).__name__}"
                )
            rows = self._pages(
                client,
                f"https://data.alpaca.markets/v1beta1/options/snapshots/{bare}",
                {**bounds, "feed": config.feed, "limit": 1000},
                "snapshots",
                config.max_contracts * 4,
            )
            for option_symbol, row in rows.items():
                result.observations.append(
                    alpaca_observation(option_symbol, symbol, row, contracts.get(option_symbol, {}), now, config.feed)
                )
        selected = set(
            expiry_priority({r.expiration for r in result.observations}, session_date)[: config.max_expirations]
        )
        result.observations = [r for r in result.observations if r.expiration in selected]
        if number(underlying_price) and underlying_price > 0:
            for row in result.observations:
                row.underlying_price = underlying_price  # Independent stock reference, not an option field.
            result.observations, coverage = select_contracts(result.observations, session_date, config)
            result.coverage.update(coverage)
        else:
            # Keep the bounded raw response until the facade can retry its stock-quote capability.
            result.coverage["selection_status"] = "deferred_missing_underlying"
        result.coverage["selected_expirations"] = sorted(d.isoformat() for d in selected)
        return result
