from datetime import date, datetime, timedelta, timezone
from math import sqrt
import pytest
from finance_analysis.options_intelligence.metrics import (
    spread,
    volume_oi,
    liquidity,
    percentile,
    skew_25,
    standard_iv,
    realized_volatility,
    oi_change,
    cohort,
    term_metrics,
)


@pytest.mark.parametrize(
    "bid,ask,expected",
    [
        (2, 3, 0.4),
        (0, 1, 2),
        (0, 0, None),
        (-1, 2, None),
        (2, 1, None),
        (None, 3, None),
        (float("nan"), 1, None),
        (1, float("inf"), None),
    ],
)
def test_spread(bid, ask, expected):
    assert spread(bid, ask) == expected


@pytest.mark.parametrize(
    "volume,oi,result",
    [(500, 100, 5), (100, 1, None), (0, 1000, None), (500, 0, None), (None, 300, None), (300, None, None)],
)
def test_volume_oi_guard(volume, oi, result, config):
    assert volume_oi(volume, oi, config) == result


def test_liquidity_unknown_stale_indicative_and_valid(observation, now, config):
    for row, reason in [
        (observation.model_copy(update={"quote_timestamp": None}), "quote_timestamp_unknown"),
        (observation.model_copy(update={"quote_timestamp": now - timedelta(hours=1)}), "stale_quote"),
        (observation.model_copy(update={"feed_type": "indicative"}), "indicative_not_nbbo"),
        (observation.model_copy(update={"quote_timestamp": now + timedelta(seconds=1)}), "stale_quote"),
    ]:
        result = liquidity(row, now, now.date(), config)
        assert result["risk"]["value"] is None
        assert result["risk"]["reason"] == reason
    result = liquidity(observation, now, now.date(), config)
    assert 0 <= result["risk"]["value"] <= 100


def test_zero_bid_low_premium_distinguished(observation, now, config):
    result = liquidity(observation.model_copy(update={"bid": 0, "ask": 0.05}), now, now.date(), config)
    assert result["spread"] == 2
    assert {"zero_bid", "very_low_premium"} <= set(result["notes"])


def test_price_dte_sensitive_allowance(observation, now, config):
    cheap = liquidity(observation.model_copy(update={"bid": 0.01, "ask": 0.03}), now, now.date(), config)
    normal = liquidity(observation, now, now.date(), config)
    near = liquidity(
        observation.model_copy(update={"expiration": now.date() + timedelta(days=3)}), now, now.date(), config
    )
    assert cheap["spread_allowance"] > normal["spread_allowance"]
    assert near["spread_allowance"] > normal["spread_allowance"]


def test_percentile_no_fake_warmup_and_ties():
    assert percentile(1, [1] * 19, 20) is None
    assert percentile(1, [1] * 20, 20) == 50
    assert percentile(2, [1] * 20, 20) == 100


def test_skew_and_interpolation(observation, now, config):
    call = observation.model_copy(update={"option_type": "call", "delta": 0.25, "iv": 0.2})
    assert skew_25([observation, call], now, config) == pytest.approx(0.1)
    puts = [
        observation.model_copy(update={"delta": -0.2, "iv": 0.28}),
        observation.model_copy(update={"delta": -0.3, "iv": 0.32}),
    ]
    assert skew_25(puts + [call], now, config) == pytest.approx(0.1)
    assert skew_25([puts[0], call], now, config) is None
    assert skew_25([observation, call.model_copy(update={"expiration": now.date()})], now, config) is None
    assert skew_25([observation, call.model_copy(update={"data_source": "yfinance"})], now, config) is None
    assert (
        skew_25([observation, call.model_copy(update={"quote_timestamp": now - timedelta(minutes=10)})], now, config)
        is None
    )


def test_no_skew_across_noncontemporaneous_ivs(observation, now, config):
    call = observation.model_copy(
        update={"option_type": "call", "delta": 0.25, "iv_timestamp": now - timedelta(seconds=121)}
    )
    assert skew_25([observation, call], now, config) is None


def test_30d_iv_total_variance():
    term = [{"dte": 20, "atm_iv": 0.2}, {"dte": 40, "atm_iv": 0.3}]
    value, method = standard_iv(term)
    assert value == pytest.approx(sqrt((0.5 * 0.2**2 * 20 + 0.5 * 0.3**2 * 40) / 30))
    assert method == "total_variance_interpolation"
    assert standard_iv(term[:1])[0] is None


def test_rv_has_exact_20_log_returns():
    assert realized_volatility([100] * 21) == 0
    assert realized_volatility([100] * 20) is None
    assert realized_volatility([100] * 20 + [None]) is None


def test_oi_only_adjacent_dated_same_source(observation, now):
    prev = observation.model_copy(update={"oi_date": date(2026, 10, 5), "open_interest": 100})
    current = observation.model_copy(update={"oi_date": date(2026, 10, 6), "open_interest": 250})
    result = oi_change(current, prev, date(2026, 10, 5), now)
    assert result["change"] == 150
    assert result["known_at"] == now.isoformat()
    for row in [
        current.model_copy(update={"oi_date": None}),
        current.model_copy(update={"oi_date": prev.oi_date}),
        current.model_copy(update={"oi_date": date(2026, 10, 8)}),
        current.model_copy(update={"data_source": "yfinance"}),
    ]:
        assert oi_change(row, prev, date(2026, 10, 5), now) is None
    assert oi_change(current, prev, date(2026, 10, 2), now) is None


def test_comparable_cohort_moves_with_underlying(observation, now):
    moved = observation.model_copy(update={"strike": 200, "underlying_price": 200})
    assert cohort(observation, now.date()) == cohort(moved, now.date())


def test_future_oi_date_uses_new_york_not_utc_day(observation):
    observed = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)  # still October 7 in New York
    previous = observation.model_copy(update={"oi_date": date(2026, 10, 7)})
    current = observation.model_copy(update={"oi_date": date(2026, 10, 8), "open_interest": 1000})
    assert oi_change(current, previous, date(2026, 10, 7), observed) is None


def test_expected_move_straddle_does_not_require_provider_iv(observation, now, config):
    put = observation.model_copy(update={"iv": None})
    call = put.model_copy(update={"option_type": "call", "bid": 3, "ask": 3.2})
    term = term_metrics([put, call], now.date(), now, config)[0]
    assert term["atm_iv"] is None
    assert term["expected_move"] == pytest.approx(5.2)
    assert term["expected_move_method"] == "atm_straddle_mid"
    old = [r.model_copy(update={"quote_timestamp": now - timedelta(minutes=10)}) for r in [put, call]]
    assert term_metrics(old, now.date(), now, config)[0]["expected_move"] is None
