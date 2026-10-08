from datetime import date, timedelta
from types import SimpleNamespace
import httpx
import pandas as pd
from finance_analysis.integrations.options.providers import (
    yahoo_observation,
    alpaca_observation,
    YahooOptionsProvider,
    AlpacaOptionsProvider,
    occ,
)
from finance_analysis.integrations.options.service import OptionsDataService
from finance_analysis.integrations.options.models import OptionChain


def test_yahoo_normalization_does_not_invent_time_or_delta(now):
    row = {
        "contractSymbol": "AAPL261106P00100000",
        "strike": 100,
        "bid": 0,
        "ask": 2,
        "contractSize": "REGULAR",
        "volume": float("nan"),
        "openInterest": 50,
        "impliedVolatility": 0.25,
        "lastTradeDate": pd.Timestamp(now),
        "lastPrice": 2.1,
    }
    result = yahoo_observation(row, "AAPL.US", date(2026, 11, 6), "put", now, now.date(), {})
    assert result.volume is None
    assert result.bid == 0
    assert result.quote_timestamp is None and result.oi_date is None and result.delta is None
    assert result.last_trade_time == now
    assert result.underlying_price is None


def test_alpaca_normalization_indicative_explicit(now):
    raw = {
        "latestQuote": {"bp": 1, "ap": 2, "bs": 12, "as": 15, "t": now.isoformat()},
        "latestTrade": {"p": 1.2, "t": now.isoformat()},
        "impliedVolatility": 0.3,
        "greeks": {"delta": -0.25, "theta": -0.1},
    }
    contract = {"size": "100", "open_interest": "200", "open_interest_date": "2026-10-06"}
    row = alpaca_observation("AAPL261106P00100000", "AAPL.US", raw, contract, now, "indicative")
    assert row.multiplier == 100 and row.oi_date == date(2026, 10, 6)
    assert row.volume is None and row.iv_timestamp is None
    assert row.delta == -0.25 and row.theta == -0.1
    assert row.feed_type == "indicative"
    assert "indicative_modified_quotes_delayed_trades" in row.limitations
    assert occ(row.symbol)[-1] == 100


def test_yahoo_expiry_selection_covers_7_30_60(now, config):
    days = [(now.date() + timedelta(days=i)).isoformat() for i in range(1, 91)]
    selected = []

    class Ticker:
        options = days

        def option_chain(self, day):
            selected.append((date.fromisoformat(day) - now.date()).days)
            return SimpleNamespace(calls=pd.DataFrame(), puts=pd.DataFrame(), underlying={})

    YahooOptionsProvider(lambda _: Ticker()).fetch("AAPL.US", now, now.date(), config)
    assert {7, 30, 60} <= set(selected)
    assert len(selected) == config.max_expirations


def test_alpaca_http_pagination_and_feed(now, config):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "paper-api.alpaca.markets":
            return httpx.Response(
                200,
                json={
                    "option_contracts": [
                        {
                            "symbol": "AAPL261106P00100000",
                            "size": "100",
                            "open_interest": "120",
                            "open_interest_date": "2026-10-06",
                        }
                    ],
                    "next_page_token": None,
                },
            )
        if "page_token" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "snapshots": {
                        "AAPL261106P00100000": {
                            "latestQuote": {"bp": 1, "ap": 2, "t": now.isoformat()},
                            "greeks": {"delta": -0.25},
                        }
                    },
                    "next_page_token": "next",
                },
            )
        return httpx.Response(200, json={"snapshots": {}, "next_page_token": None})

    provider = AlpacaOptionsProvider(key="test", secret="test", transport=httpx.MockTransport(handle))
    result = provider.fetch("AAPL.US", now, now.date(), config, underlying_price=100)
    assert len(result.observations) == 1
    assert all(r.url.params["feed"] == "indicative" for r in calls[1:])
    assert calls[0].url.params["expiration_date_lte"] == "2027-01-05"
    assert calls[1].url.params["strike_price_gte"] == "70.0"


def test_primary_and_capability_fallback_remain_separate(observation, now, config):
    yahoo = observation.model_copy(
        update={
            "data_source": "yfinance",
            "feed_type": "delayed",
            "delta": None,
            "quote_timestamp": None,
            "open_interest": 100,
        }
    )
    fallback = observation.model_copy(update={"volume": None, "open_interest": 1000})

    class Provider:
        def __init__(self, row):
            self.row = row

        def fetch(self, symbol, now, day, config, **kwargs):
            return OptionChain(symbol=symbol, observed_at=now, observations=[self.row])

    result = OptionsDataService(Provider(yahoo), Provider(fallback), cache=False, config=config).fetch("AAPL.US", now)
    assert [(r.data_source, r.open_interest) for r in result.observations] == [("yfinance", 100), ("alpaca", 1000)]


def test_cache_preserves_source_observation_time(observation, now, config):
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])

    class Cache:
        def get(self, _):
            return chain.model_dump_json()

    class Fail:
        def fetch(self, *_):
            raise AssertionError("cache should avoid repeated fetch")

    result = OptionsDataService(Fail(), Fail(), Cache(), config).fetch("AAPL.US", now + timedelta(minutes=2))
    assert result.observed_at == now
    assert result.observations[0].quote_timestamp == now


def test_alpaca_dated_daily_bar_without_iv_is_available(now):
    raw = {
        "dailyBar": {"t": "2026-10-07T04:00:00Z", "v": 120, "vw": 2.5},
        "latestQuote": {"bp": 2, "ap": 3, "t": now.isoformat()},
    }
    contract = {"size": "100", "multiplier": "100", "open_interest_date": "2026-10-06", "open_interest": "110"}
    row = alpaca_observation("AAPL261106P00100000", "AAPL.US", raw, contract, now, "indicative")
    assert row.volume == 120 and row.volume_date == date(2026, 10, 7)
    assert row.iv is None and row.delta is None and row.traded_price is None
    assert "greeks_unavailable" in row.limitations
    opra = alpaca_observation("AAPL261106P00100000", "AAPL.US", raw, contract, now, "opra")
    assert opra.traded_price == 2.5 and opra.traded_price_method == "reported_daily_vwap"
