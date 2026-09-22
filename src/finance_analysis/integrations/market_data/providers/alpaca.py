"""Batch, forward-adjusted US daily bars from Alpaca's consolidated SIP feed."""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from finance_analysis.core.retry import retry_call, transient_response

from finance_analysis.core.time import day_bounds_utc, utc_now
from finance_analysis.market_review.trading_calendar import get_trading_days_between

from ..batch_pacing import before_daily_batch, daily_batch_scope
from ..models import Adjustment, BatchBarResult, DailyBarsRequest, Market, MarketBar
from ..normalizer import canonical_symbol
from ..validator import validate_bars

logger = logging.getLogger(__name__)
BAR_URL = "https://data.alpaca.markets/v2/stocks/bars"
US_TIMEZONE = ZoneInfo("America/New_York")


class AlpacaHTTPError(ValueError):
    def __init__(self, response: httpx.Response):
        self.status_code = response.status_code
        category = "request_failed"
        if self.status_code == 401:
            category = "credentials_invalid: check ALPACA_API_KEY and ALPACA_SECRET_KEY"
        elif self.status_code == 403:
            try:
                payload = response.json()
                message = str(payload.get("message", "")).lower() if isinstance(payload, dict) else ""
            except ValueError:
                message = ""
            if "sip" in message and any(word in message for word in ("subscription", "permit", "permission")):
                category = "sip_permission_denied: check SIP subscription and historical request end time"
            elif any(
                word in message for word in ("credential", "api key", "api-key", "unauthorized", "authentication")
            ):
                category = "credentials_invalid: check ALPACA_API_KEY and ALPACA_SECRET_KEY"
            else:
                category = "access_forbidden: check credentials and market-data permissions"
        # Only emit our classification, never the upstream body (which may contain secrets).
        super().__init__(f"{category} (Alpaca HTTP {self.status_code})")


class AlpacaProvider:
    name = "alpaca"

    def __init__(
        self, *, api_key: str | None = None, secret_key: str | None = None, batch_size: int = 100,
        timeout: float = 20.0, transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not 1 <= batch_size <= 100:
            raise ValueError("Alpaca batch_size must be between 1 and 100")
        if timeout <= 0:
            raise ValueError("Alpaca timeout must be positive")
        self._api_key = (api_key or "").strip()
        self._secret_key = (secret_key or "").strip()
        self.batch_size = batch_size
        self.timeout = timeout
        self._transport = transport

    @staticmethod
    def _bar(symbol: str, row: dict) -> MarketBar:
        timestamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Alpaca timestamp must be timezone-aware")
        volume = float(row["v"])
        if not math.isfinite(volume) or volume < 0 or not volume.is_integer():
            raise ValueError("Alpaca volume must be a nonnegative share count")
        return MarketBar(
            symbol=symbol, market=Market.US, interval="1d",
            trade_date=timestamp.astimezone(US_TIMEZONE).date(), bar_time=None,
            open=float(row["o"]), high=float(row["h"]), low=float(row["l"]), close=float(row["c"]),
            volume=int(volume), amount=None, currency="USD", adjustment=Adjustment.FORWARD, provider="alpaca",
        )

    def _fetch_batch(self, client, symbols, request, start, end):
        params = {
            "symbols": ",".join(symbol.removesuffix(".US") for symbol in symbols),
            "timeframe": "1Day", "start": start.isoformat(), "end": end.isoformat(),
            "feed": "sip", "adjustment": "all", "sort": "asc", "limit": 10000,
        }
        rows = {symbol: [] for symbol in symbols}
        invalid = set()
        seen_tokens = set()
        for _ in range(1000):
            response = retry_call(lambda: client.get(BAR_URL, params=params), retry_result=transient_response)
            if response.status_code != 200:
                # Do not expose headers or untrusted upstream response bodies in task logs.
                raise AlpacaHTTPError(response)
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
                raise ValueError("Invalid Alpaca bars response")
            for symbol in symbols:
                values = payload["bars"].get(symbol.removesuffix(".US"), [])
                if not isinstance(values, list):
                    invalid.add(symbol)
                else:
                    rows[symbol].extend(values)
            token = payload.get("next_page_token")
            if token is None:
                break
            if not isinstance(token, str) or not token or token in seen_tokens:
                raise ValueError("Invalid or repeated Alpaca page token")
            seen_tokens.add(token)
            params["page_token"] = token
        else:
            raise ValueError("Alpaca pagination limit exceeded")
        result = BatchBarResult()
        sessions = set(get_trading_days_between("us", request.start_date, request.end_date))
        for symbol, values in rows.items():
            try:
                if symbol in invalid:
                    raise ValueError("Invalid symbol bars")
                bars = validate_bars(self._bar(symbol, row) for row in values)
                if any(not request.start_date <= bar.trade_date <= request.end_date for bar in bars):
                    raise ValueError("Bar outside requested dates")
                if len({bar.trade_date for bar in bars}) != len(bars):
                    raise ValueError("Duplicate daily bars")
                if bars:
                    returned_dates = {bar.trade_date for bar in bars}
                    expected_dates = {day for day in sessions if day >= min(returned_dates)}
                    if expected_dates - returned_dates:
                        result.failed_symbols[symbol] = "incomplete_daily_window"
                        continue
                    result.data[symbol] = sorted(bars, key=lambda bar: bar.trade_date)
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                result.failed_symbols[symbol] = "invalid_daily_bars"
        return result

    @daily_batch_scope()
    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.FORWARD:
            raise ValueError("Alpaca daily bars require adjustment='forward'")
        started = monotonic()
        symbols = list(dict.fromkeys(canonical_symbol(code) for code in request.symbols))
        result = BatchBarResult()
        supported = []
        for symbol in symbols:
            if re.fullmatch(r"[A-Z][A-Z0-9.\-]*\.US", symbol):
                supported.append(symbol)
            else:
                result.failed_symbols[symbol] = "unsupported_symbol"
        if not self._api_key or not self._secret_key:
            result.failed_symbols.update({symbol: "credentials_not_configured" for symbol in supported})
        elif supported:
            start, _ = day_bounds_utc(request.start_date, "America/New_York")
            _, end = day_bounds_utc(request.end_date, "America/New_York")
            # Basic accounts can read historical SIP, but not the most recent 15 minutes.
            end = min(end - timedelta(microseconds=1), utc_now() - timedelta(minutes=16))
            if end < start:
                result.failed_symbols.update({symbol: "historical_window_not_available" for symbol in supported})
            else:
                with httpx.Client(
                    headers={"APCA-API-KEY-ID": self._api_key, "APCA-API-SECRET-KEY": self._secret_key},
                    timeout=self.timeout, transport=self._transport,
                ) as client:
                    for offset in range(0, len(supported), self.batch_size):
                        batch = supported[offset:offset + self.batch_size]
                        before_daily_batch()
                        try:
                            fetched = self._fetch_batch(client, batch, request, start, end)
                        except (httpx.HTTPError, ValueError) as exc:
                            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                            # Discard incomplete pages: fallback fetches the entire symbol window.
                            result.failed_symbols.update({symbol: reason for symbol in batch})
                            if isinstance(exc, AlpacaHTTPError) and exc.status_code in {401, 403}:
                                result.failed_symbols.update({symbol: reason for symbol in supported[offset:]})
                                break
                            continue
                        result.data.update(fetched.data)
                        result.providers_used.update(fetched.providers_used)
                        result.missing_symbols.extend(fetched.missing_symbols)
                        result.failed_symbols.update(fetched.failed_symbols)
        logger.log(
            logging.WARNING if result.failed_symbols or result.missing_symbols else logging.INFO,
            "provider=alpaca market=US symbol_count=%s success_count=%s failed_count=%s missing_count=%s "
            "fallback_pending_count=%s elapsed_seconds=%.3f",
            len(symbols), len(result.data), len(result.failed_symbols), len(result.missing_symbols),
            len(symbols) - len(result.data), monotonic() - started,
        )
        return result
