from datetime import timedelta
import pytest
from finance_analysis.integrations.options.models import OptionChain
from finance_analysis.options_intelligence.engine import analyze


def yahoo(row):
    return row.model_copy(
        update={
            "data_source": "yfinance",
            "feed_type": "delayed",
            "delta": None,
            "quote_timestamp": None,
            "iv_timestamp": None,
            "volume_date": row.observed_at.date(),
            "limitations": ["quote_timestamp_unknown", "oi_as_of_unknown"],
        }
    )


def test_warmup_scores_separate_and_null(observation, now, config):
    row = yahoo(observation).model_copy(update={"volume": 10, "open_interest": 1})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row]), now.date(), now, [], "daily", config
    )
    assert result["evidence_grade"] == "C"
    assert result["iv_percentile"] is None
    assert result["skew_30d"] is None
    assert result["scores"]["bearish_demand"]["value"] is None
    assert result["scores"]["unusual_activity"]["value"] is None
    assert result["scores"]["liquidity_risk"]["value"] is not None
    assert "total_score" not in result


def test_no_actual_premium_from_mid_or_latest_trade(observation, now, config):
    row = yahoo(observation)
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row]), now.date(), now, [], "daily", config
    )
    assert result["contracts"][0]["premium_volume"] is None
    assert result["contracts"][0]["premium_estimate"] == 500 * 2.1 * 100
    assert result["scores"]["unusual_activity"]["method"] == "initial_absolute_volume_oi_rules"
    assert result["scores"]["liquidity_risk"]["value"] is not None
    assert result["scores"]["liquidity_risk"]["method"] == "observed_quote_liquidity_rules"


def test_history_uses_only_prior_same_phase_source_cohorts(observation, now, config):
    row = yahoo(observation)
    history = []
    for i in range(1, 21):
        day = now.date() - timedelta(days=i)
        old = row.model_copy(update={"expiration": day + timedelta(days=30), "volume": 100, "volume_date": day})
        history.append({"trade_date": day, "mode": "daily", "rows": [old], "metrics": {}})
    chain = OptionChain(
        symbol="AAPL.US", observed_at=now, observations=[row], errors=["alpaca:credentials_not_configured"]
    )
    result = analyze(chain, now.date(), now, history, "daily", config)
    assert result["contracts"][0]["volume_percentile"] == 100
    assert result["evidence_grade"] == "C"  # single Put has no valid 30D ATM IV
    assert any(e["event_type"] == "PUT_VOLUME_SPIKE" for e in result["events"])
    intraday = analyze(chain, now.date(), now, history, "14:00", config)
    assert intraday["contracts"][0]["volume_percentile"] is None
    same_day = [{**h, "trade_date": now.date()} for h in history]
    assert analyze(chain, now.date(), now, same_day, "daily", config)["history_days"] == 0


def test_stale_volume_never_scores_current_session(observation, now, config):
    row = yahoo(observation).model_copy(update={"volume": 100000, "volume_date": now.date() - timedelta(days=1)})
    history = []
    for i in range(1, 21):
        day = now.date() - timedelta(days=i)
        old = row.model_copy(update={"expiration": day + timedelta(days=30), "volume": 100, "volume_date": day})
        history.append({"trade_date": day, "mode": "daily", "rows": [old], "metrics": {}})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row]), now.date(), now, history, "daily", config
    )
    contract = result["contracts"][0]
    assert contract["volume"] == 100000  # Preserve source facts and their date.
    assert contract["volume_percentile"] is None
    assert contract["volume_oi"] is None
    assert contract["premium_estimate"] is None
    assert not any(
        e["event_type"] in {"PUT_VOLUME_SPIKE", "VOLUME_OI_ANOMALY", "LARGE_PREMIUM_ACTIVITY"} for e in result["events"]
    )


def test_indicative_never_scores_real_liquidity(observation, now, config):
    row = observation.model_copy(update={"feed_type": "indicative"})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row]), now.date(), now, [], "daily", config
    )
    assert result["scores"]["liquidity_risk"]["value"] is not None
    assert result["scores"]["liquidity_risk"]["method"] == "observed_quote_liquidity_rules"
    assert result["order_flow"]["available"] is False
    assert not any(e["event_type"] == "WIDE_BID_ASK_SPREAD" for e in result["events"])


def test_fallback_quotes_do_not_replace_primary_volume(observation, now, config):
    primary = yahoo(observation).model_copy(update={"volume": 200})
    fallback = observation.model_copy(update={"volume": None, "open_interest": 123})
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[primary, fallback])
    result = analyze(chain, now.date(), now, [], "daily", config)
    assert result["volume_source"] == "yfinance"
    assert len(result["contracts"]) == 2
    assert result["contracts"][0]["open_interest"] == 100
    assert result["contracts"][1]["volume"] is None


def test_actual_daily_premium_requires_dated_real_vwap(observation, now, config):
    row = observation.model_copy(
        update={"traded_price": 2.5, "traded_price_method": "reported_daily_vwap", "volume_date": now.date()}
    )
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[row])
    result = analyze(chain, now.date(), now, [], "daily", config)
    assert result["premium_volume"] == 500 * 2.5 * 100
    assert result["contracts"][0]["premium_volume"] == 500 * 2.5 * 100
    chain.observations = [row.model_copy(update={"feed_type": "indicative"})]
    assert analyze(chain, now.date(), now, [], "daily", config)["premium_volume"] is None


def test_volume_oi_capability_falls_back_without_stitching(observation, now, config):
    primary = yahoo(observation).model_copy(update={"open_interest": 0, "volume": 500})
    fallback = observation.model_copy(update={"feed_type": "indicative", "open_interest": 100, "volume": 600})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[primary, fallback]),
        now.date(),
        now,
        [],
        "daily",
        config,
    )
    assert result["scores"]["unusual_activity"]["value"] is not None
    assert result["activity_sources"] == ["alpaca:indicative"]
    assert result["contracts"][0]["volume_oi"] is None
    assert result["contracts"][1]["volume_oi"] == 6
    assert result["evidence_grade"] == "C"


def test_evidence_b_and_a_need_real_comparable_iv_history(observation, now, config):
    put = observation.model_copy(update={"volume": 500, "volume_date": now.date()})
    call = observation.model_copy(
        update={"symbol": "AAPL261106C00100000", "option_type": "call", "delta": 0.25, "iv": 0.25, "volume": 100}
    )
    history = []
    for i in range(20, 0, -1):
        day = now.date() - timedelta(days=i)
        history.append(
            {
                "trade_date": day,
                "mode": "daily",
                "rows": [
                    put.model_copy(update={"expiration": day + timedelta(days=30), "volume": 100, "volume_date": day}),
                    call.model_copy(update={"expiration": day + timedelta(days=30), "volume_date": day}),
                ],
                "metrics": {
                    "iv_30d": 0.27,
                    "iv_source": ["alpaca", "opra"],
                    "volume_source": "alpaca",
                    "volume_feed": "opra",
                },
            }
        )
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[put, call])
    assert analyze(chain, now.date(), now, history, "daily", config)["evidence_grade"] == "A"
    chain.observations = [r.model_copy(update={"iv_timestamp": None}) for r in [put, call]]
    assert analyze(chain, now.date(), now, history, "daily", config)["evidence_grade"] == "B"
    chain.observations = [r.model_copy(update={"feed_type": "indicative"}) for r in [put, call]]
    assert analyze(chain, now.date(), now, history, "daily", config)["evidence_grade"] == "C"


def test_iv30_falls_back_when_primary_only_has_short_tenor(observation, now, config):
    short_put = yahoo(observation).model_copy(update={"expiration": now.date() + timedelta(days=7)})
    short_call = short_put.model_copy(update={"symbol": "AAPL261014C00100000", "option_type": "call"})
    call = observation.model_copy(
        update={"symbol": "AAPL261106C00100000", "option_type": "call", "delta": 0.25, "iv": 0.2}
    )
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[short_put, short_call, observation, call]),
        now.date(),
        now,
        [],
        "daily",
        config,
    )
    assert result["iv_30d"] == 0.25
    assert result["iv_source"] == ["alpaca", "opra"]
    assert result["put_iv_source"] == ["alpaca", "opra"]


def test_skew_uses_valid_nearby_expiry_and_falls_back_per_tenor(observation, now, config):
    short = [
        r.model_copy(
            update={"data_source": "yfinance", "feed_type": "delayed", "expiration": now.date() + timedelta(days=7)}
        )
        for r in [observation, observation.model_copy(update={"option_type": "call", "delta": 0.25, "iv": 0.2})]
    ]
    near = [
        r.model_copy(update={"expiration": now.date() + timedelta(days=28)})
        for r in [observation, observation.model_copy(update={"option_type": "call", "delta": 0.25, "iv": 0.2})]
    ]
    invalid_exact = observation.model_copy(update={"delta": None})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=short + near + [invalid_exact]),
        now.date(),
        now,
        [],
        "daily",
        config,
    )
    assert result["skew_terms"][0]["source"] == "yfinance"
    assert result["skew_terms"][1]["source"] == "alpaca"
    assert result["skew_terms"][1]["actual_dte"] == 28
    assert result["skew_30d"] == pytest.approx(0.1)


def test_call_only_oi_increase_does_not_create_bearish_zero(observation, now, config):
    row = yahoo(observation).model_copy(
        update={"symbol": "AAPL261106C00100000", "option_type": "call", "volume": None, "iv": None}
    )
    change = {"change": 200, "previous": 100, "oi_date": "2026-10-06", "source": "yfinance"}
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row]),
        now.date(),
        now,
        [],
        "daily",
        config,
        oi_changes={(row.symbol, "yfinance", "delayed"): change},
    )
    assert result["scores"]["unusual_activity"]["value"] is not None
    assert result["scores"]["bearish_demand"]["value"] is None


def test_liquidity_event_has_risk_direction_and_volume_event_uses_observation_time(observation, now, config):
    row = observation.model_copy(update={"bid": 0, "ask": 10, "quote_timestamp": now - timedelta(seconds=100)})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row]), now.date(), now, [], "daily", config
    )
    wide = next(e for e in result["events"] if e["event_type"] == "WIDE_BID_ASK_SPREAD")
    activity = next(e for e in result["events"] if e["event_type"] == "VOLUME_OI_ANOMALY")
    assert wide["direction"] == "liquidity_risk"
    assert activity["data_time"] == row.observed_at.isoformat()
    assert activity["volume_date"] == now.date().isoformat()
