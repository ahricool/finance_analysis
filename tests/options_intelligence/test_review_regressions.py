from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.integrations.options.models import OptionChain
from finance_analysis.integrations.options.providers import YahooOptionsProvider, select_contracts
from finance_analysis.integrations.options.service import OptionsDataService, limit_chain
from finance_analysis.options_intelligence.engine import analyze
from finance_analysis.options_intelligence.evaluation import evaluate


def option(observation, now, dte=30, kind="put", strike=100, source="alpaca", **fields):
    expiry = now.date() + timedelta(days=dte)
    return observation.model_copy(
        update={
            "symbol": f"AAPL{expiry:%y%m%d}{'P' if kind == 'put' else 'C'}{int(strike * 1000):08d}",
            "expiration": expiry,
            "option_type": kind,
            "strike": strike,
            "data_source": source,
            "feed_type": "delayed" if source == "yfinance" else "opra",
            "underlying_timestamp": now,
            "delta": -0.25 if kind == "put" else 0.25,
            **fields,
        }
    )


def pair(observation, now, dte, source="alpaca", iv=0.3):
    return [option(observation, now, dte, kind, source=source, iv=iv) for kind in ("call", "put")]


def metrics(rows, now, config, history=()):
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=rows)
    return analyze(chain, now.date(), now, history, "daily", config)


@pytest.mark.parametrize("budget", [6, 18, 36])
def test_yahoo_dense_near_month_does_not_erase_core_tenors(now, config, budget):
    expiries = [now.date() + timedelta(days=d) for d in (1, 2, 3, 7, 30, 60)]
    requests = []

    class Ticker:
        options = [d.isoformat() for d in expiries]

        def option_chain(self, day):
            requests.append(day)
            expiry = date.fromisoformat(day)
            strikes = range(70, 131) if (expiry - now.date()).days <= 7 else (80, 90, 95, 100, 105, 110, 120)
            frames = []
            for kind in ("C", "P"):
                frames.append(
                    pd.DataFrame(
                        [
                            {
                                "contractSymbol": f"AAPL{expiry:%y%m%d}{kind}{strike * 1000:08d}",
                                "strike": strike,
                                "contractSize": "REGULAR",
                                "bid": 2,
                                "ask": 3,
                                "volume": 200,
                                "lastTradeDate": now,
                                "openInterest": 100,
                                "impliedVolatility": 0.3,
                            }
                            for strike in strikes
                        ]
                    )
                )
            return SimpleNamespace(
                calls=frames[0],
                puts=frames[1],
                underlying={"regularMarketPrice": 100, "regularMarketTime": now.timestamp()},
            )

    bounded = replace(config, max_contracts=budget)
    chain = YahooOptionsProvider(lambda _: Ticker()).fetch("AAPL.US", now, now.date(), bounded)
    assert len(chain.observations) == budget
    assert len(requests) <= config.max_expirations
    for dte in (7, 30, 60):
        rows = [r for r in chain.observations if r.expiration == now.date() + timedelta(days=dte)]
        assert {r.option_type for r in rows} == {"call", "put"}
        assert all(any(r.option_type == kind and r.strike == 100 for r in rows) for kind in ("call", "put"))
        if budget == 36:
            assert any(r.option_type == "call" and r.strike > 100 for r in rows)
            assert any(r.option_type == "put" and r.strike < 100 for r in rows)
    assert chain.coverage["truncated_contracts"]
    assert len(chain.coverage["covered_expirations"]) <= config.max_expirations


def test_small_budget_protects_30d_bracket_and_known_delta_otm(observation, now, config):
    rows = [
        option(observation, now, dte, kind, strike, delta=delta)
        for dte in (1, 7, 20, 40, 60)
        for kind, strike, delta in [
            ("call", 100, 0.5),
            ("put", 100, -0.5),
            ("call", 105, 0.25),
            ("put", 95, -0.25),
            ("call", 110, 0.1),
            ("put", 90, -0.1),
        ]
    ]
    selected, coverage = select_contracts(rows, now.date(), replace(config, max_contracts=8))
    assert len(selected) == 8
    assert {20, 40} <= {(r.expiration - now.date()).days for r in selected}
    # A four-contract budget per expiry retains both ATM and the supplied 25Δ OTM legs.
    selected, _ = select_contracts(rows, now.date(), replace(config, max_contracts=20))
    for dte in (20, 40):
        assert {100, 105, 95} <= {r.strike for r in selected if r.expiration == now.date() + timedelta(days=dte)}
    assert coverage["selection_status"] == "limited"


def test_two_contract_budget_keeps_nearest_shared_atm_strike(observation, now, config):
    rows = [
        option(observation, now, kind=kind, strike=strike)
        for kind, strike in [("call", 99), ("call", 101), ("put", 99), ("put", 100)]
    ]
    selected, _ = select_contracts(rows, now.date(), replace(config, max_contracts=2))
    assert len(selected) == 2
    assert {r.strike for r in selected} == {99}
    assert {r.option_type for r in selected} == {"call", "put"}


class FailedYahoo:
    def fetch(self, *args):
        raise ValueError("Yahoo unavailable")


class RawAlpaca:
    def __init__(self, rows):
        self.rows, self.spots = rows, []

    def fetch(self, symbol, now, day, config, underlying_price=None):
        self.spots.append(underlying_price)
        return OptionChain(symbol=symbol, observed_at=now, observations=self.rows)


def quote(now, price=100):
    return SimpleNamespace(data={"AAPL.US": SimpleNamespace(price=price, quote_time=now, provider="longbridge")})


def test_facade_supplies_existing_stock_quote_without_options_recursion(monkeypatch, observation, now, config):
    from finance_analysis.integrations.options import service as data

    rows = [
        option(observation, now, kind=kind, strike=strike, underlying_price=None)
        for kind in ("call", "put")
        for strike in (10, 20, 80, 90, 100, 110, 120, 200)
    ]
    alpaca = RawAlpaca(rows)
    actual = OptionsDataService
    factory = lambda **kw: actual(FailedYahoo(), alpaca, cache=False, config=replace(config, max_contracts=4), **kw)
    monkeypatch.setattr(data, "OptionsDataService", factory)
    market = MarketDataService.__new__(MarketDataService)
    market.get_realtime_quotes = Mock(return_value=quote(now))
    chain = market.get_option_chain("AAPL.US", now=now)
    assert alpaca.spots == [100]
    market.get_realtime_quotes.assert_called_once_with(["AAPL.US"])
    assert len(chain.observations) == 4
    assert sum(r.strike == 100 for r in chain.observations) == 2
    assert all(70 <= r.strike <= 130 for r in chain.observations)
    assert all(
        r.underlying_timestamp == now and "underlying_price_source:longbridge" in r.limitations
        for r in chain.observations
    )
    assert all(r.data_source == "alpaca" and r.iv == observation.iv for r in chain.observations)


def test_late_stock_reference_reselects_raw_contracts(observation, now, config):
    rows = [
        option(observation, now, kind=kind, strike=strike, underlying_price=None)
        for kind in ("call", "put")
        for strike in (10, 20, 80, 90, 100, 110, 120, 200)
    ]
    loader = Mock(side_effect=[SimpleNamespace(data={}), quote(now)])
    alpaca = RawAlpaca(rows)
    chain = OptionsDataService(
        FailedYahoo(), alpaca, cache=False, config=replace(config, max_contracts=4), underlying_quote_loader=loader
    ).fetch("AAPL.US", now)
    assert alpaca.spots == [None]
    assert loader.call_count == 2
    assert len(chain.observations) == 4
    assert sum(r.strike == 100 for r in chain.observations) == 2
    assert all(r.strike >= 70 for r in chain.observations)
    original = chain.coverage["retained_by_source"]["alpaca:opra"]
    limit_chain(chain, now.date(), replace(config, max_contracts=4))
    coverage = chain.coverage["retained_by_source"]["alpaca:opra"]
    assert coverage["truncated_contracts"] and coverage["selection_status"] == "limited"
    assert coverage["eligible_contract_count"] == original["eligible_contract_count"] > 4


@pytest.mark.parametrize("quote_delay,available", [(2, True), (10, False)])
def test_stock_reference_uses_fetch_completion_time(monkeypatch, observation, now, config, quote_delay, available):
    from finance_analysis.integrations.options import service as data

    monkeypatch.setattr(data, "utc_now", lambda: now + timedelta(seconds=5))
    rows = [option(observation, now, underlying_price=None)]
    chain = OptionsDataService(
        FailedYahoo(),
        RawAlpaca(rows),
        cache=False,
        config=config,
        underlying_quote_loader=Mock(return_value=quote(now + timedelta(seconds=quote_delay))),
    ).fetch("AAPL.US", now)
    assert (chain.observations[0].underlying_price is not None) is available
    if available:
        assert chain.observations[0].underlying_timestamp == now + timedelta(seconds=quote_delay)


@pytest.mark.parametrize("price", [None, 0, -1, float("nan")])
def test_missing_or_invalid_stock_reference_never_computes_moneyness(observation, now, config, price):
    rows = [option(observation, now, kind=kind, underlying_price=price) for kind in ("call", "put")]
    chain = OptionsDataService(
        FailedYahoo(),
        RawAlpaca(rows),
        cache=False,
        config=config,
        underlying_quote_loader=Mock(return_value=quote(now, price)),
    ).fetch("AAPL.US", now)
    result = metrics(chain.observations, now, config)
    assert result["iv_30d"] is None
    assert result["term_structure"] == []
    assert result["put_iv"] is None
    assert result["underlying_price"] is None
    assert "underlying_price_missing" in result["limitations"]
    assert all(r.underlying_price is None for r in chain.observations)


def test_missing_spot_and_over_budget_does_not_return_low_strike_prefix(observation, now, config):
    rows = [option(observation, now, strike=strike, underlying_price=None) for strike in range(1, 20)]
    chain = OptionsDataService(
        FailedYahoo(),
        RawAlpaca(rows),
        cache=False,
        config=replace(config, max_contracts=4),
        underlying_quote_loader=Mock(return_value=SimpleNamespace(data={})),
    ).fetch("AAPL.US", now)
    assert chain.observations == []
    assert "underlying_price_missing_contract_selection_unavailable" in chain.errors
    assert chain.coverage["retained_by_source"]["alpaca:opra"]["moneyness_filter_applied"] is False


def test_one_old_volume_does_not_poison_hundred_current_contracts(observation, now, config):
    rows = [
        option(observation, now, kind=kind, strike=80 + i, volume=200 if kind == "put" else 100)
        for kind in ("call", "put")
        for i in range(50)
    ]
    stale = option(observation, now, kind="call", strike=140, volume=999999, volume_date=now.date() - timedelta(days=1))
    result = metrics(rows + [stale], now, config)
    assert result["put_call_volume_ratio"] == 2
    coverage = result["coverage"]["put_call_volume"][2]
    assert coverage["valid_call_contracts"] == coverage["valid_put_contracts"] == 50
    assert coverage["call_valid_fraction"] == pytest.approx(50 / 51)
    assert result["evidence_grade"] == "C"
    assert result["scores"]["bearish_demand"]["confidence"] == "low"
    assert stale.volume == 999999  # Raw observations were not rewritten.


@pytest.mark.parametrize("case", ["unknown_dates", "missing_calls", "zero_calls", "negative_calls"])
def test_invalid_volume_cannot_supply_ratio_denominator(observation, now, config, case):
    call, put = pair(observation, now, 30)
    if case == "unknown_dates":
        rows = [r.model_copy(update={"volume_date": None}) for r in (put, call)]
    else:
        call = call.model_copy(update={"volume": {"missing_calls": None, "zero_calls": 0, "negative_calls": -1}[case]})
        rows = [put, call]
    assert metrics(rows, now, config)["put_call_volume_ratio"] is None


def test_sparse_volume_coverage_is_explicitly_low_confidence(observation, now, config):
    rows = [
        option(observation, now, kind=kind, strike=80 + i, volume_date=now.date() if i == 0 else None)
        for kind in ("call", "put")
        for i in range(50)
    ]
    result = metrics(rows, now, config)
    assert result["put_call_volume_ratio"] == 1
    coverage = result["coverage"]["put_call_volume"][2]
    assert coverage["call_valid_fraction"] == coverage["put_valid_fraction"] == 0.02
    assert coverage["confidence"] == "low" and result["confidence"] == "low"
    assert result["evidence_grade"] == "C"


def test_volume_ratio_uses_one_source_feed_and_no_duplicate_contracts(observation, now, config):
    yahoo = pair(observation, now, 30, source="yfinance")
    yahoo[0].volume, yahoo[1].volume = 100, 200
    fallback = pair(observation, now, 30)
    fallback[0].volume, fallback[1].volume = 1000, 100
    result = metrics(yahoo + fallback + [yahoo[1], yahoo[0].model_copy(update={"volume_date": None})], now, config)
    assert result["put_call_volume_ratio"] == 2
    assert result["coverage"]["put_call_volume"][2]["source"] == "yfinance"
    assert result["coverage"]["put_call_volume"][2]["duplicate_contracts_excluded"] == 2


def test_displayed_terms_include_fallback_iv30_and_far_expiry(observation, now, config):
    rows = (
        pair(observation, now, 7, "yfinance", 0.6)
        + pair(observation, now, 30, iv=0.3)
        + pair(observation, now, 60, iv=0.32)
    )
    result = metrics(rows, now, config)
    assert [(t["dte"], t["source"]) for t in result["term_structure"]] == [
        (7, "yfinance"),
        (30, "alpaca"),
        (60, "alpaca"),
    ]
    assert result["iv_30d"] == pytest.approx(0.3) and result["iv_source"] == ["alpaca", "opra"]
    assert not any(e["event_type"] == "IV_TERM_INVERSION" for e in result["events"])
    assert len(result["coverage"]["provider_term_structure"]["alpaca:opra"]) == 2


def test_iv30_cannot_interpolate_across_sources_or_feeds(observation, now, config):
    for source, feed in (("yfinance", "delayed"), ("alpaca", "indicative")):
        front = [r.model_copy(update={"feed_type": feed}) for r in pair(observation, now, 20, source, 0.7)]
        result = metrics(front + pair(observation, now, 40, iv=0.2), now, config)
        assert result["iv_30d"] is None
        assert not any(e["event_type"] == "IV_TERM_INVERSION" for e in result["events"])


def test_iv30_reference_bracket_is_visible_and_same_source(observation, now, config):
    rows = (
        pair(observation, now, 20, "yfinance", 0.8)
        + pair(observation, now, 20, iv=0.3)
        + pair(observation, now, 40, iv=0.4)
    )
    result = metrics(rows, now, config)
    assert result["iv_source"] == ["alpaca", "opra"]
    assert all(t["source"] == "alpaca" for t in result["term_structure"])
    assert result["iv_30d"] == pytest.approx(((0.3**2 * 20 + 0.4**2 * 40) / 60) ** 0.5)
    assert len(result["coverage"]["iv_30d_reference_expirations"]) == 2
    assert result["coverage"]["provider_term_structure"]["yfinance:delayed"][0]["atm_iv"] == 0.8


def test_actual_same_source_inversion_is_retained(observation, now, config):
    result = metrics(
        pair(observation, now, 7, "yfinance", 0.2)
        + pair(observation, now, 30, iv=0.6)
        + pair(observation, now, 60, iv=0.3),
        now,
        config,
    )
    event = next(e for e in result["events"] if e["event_type"] == "IV_TERM_INVERSION")
    assert event["source"] == "alpaca" and event["value"] == pytest.approx(0.3)
    assert event["reference"]["front"]["dte"] == 30


@pytest.mark.parametrize(
    "local,entry",
    [
        ("2026-10-05T08:00:00", "2026-10-05"),
        ("2026-10-05T10:00:00", "2026-10-06"),
        ("2026-10-05T17:00:00", "2026-10-06"),
        ("2026-10-09T17:00:00", "2026-10-12"),
        ("2026-07-02T17:00:00", "2026-07-06"),
        ("2026-07-03T08:00:00", "2026-07-06"),
        ("2026-10-10T08:00:00", "2026-10-12"),
        ("2026-03-09T08:00:00", "2026-03-09"),
        ("2026-03-09T09:30:00", "2026-03-10"),
        ("2026-11-27T08:00:00", "2026-11-27"),
        ("2026-11-27T12:00:00", "2026-11-30"),
        ("2026-11-27T13:30:00", "2026-11-30"),
    ],
)
def test_evaluation_uses_first_effective_open_after_event(local, entry):
    known = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    event = {"symbol": "AAPL.US", "occurred_at": known, "initial_evidence": {}}
    expected = date.fromisoformat(entry)
    bars = {
        "AAPL.US": {expected: {"open": 100, "close": 105, "low": 95}},
        "SPY.US": {expected: {"open": 200, "close": 202, "low": 199}},
    }
    result = evaluate(event, bars, known + timedelta(days=7))
    assert result["entry_date"] == entry
    assert result["returns"][0]["value"] == pytest.approx(0.05)
    assert result["benchmarks"]["SPY.US"][0]["value"] == pytest.approx(0.01)
    assert event["initial_evidence"] == {}
