from dataclasses import replace
from datetime import date, timedelta

import pandas as pd
import pytest

from finance_analysis.analysis.technical.indicators import rsi_series
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.mean_reversion import calculate_mean_reversion
from finance_analysis.trend_following.models import DailyBar


def history(closes):
    return [
        DailyBar(date(2026, 1, 1) + timedelta(days=i), close - 0.2, close + 0.2, close - 0.8, close, 1000)
        for i, close in enumerate(closes)
    ]


def evaluate(bars, **kwargs):
    return calculate_mean_reversion(bars, calculate_features(bars), **kwargs)


def falling():
    return [100 + (i % 2) * 0.2 for i in range(40)] + [99, 97, 95, 92, 88]


def test_wilder_seed_and_existing_rolling_rsi_preserved():
    prices = pd.Series([100, 101, 103, 102, 99, 98, 100, 103, 102, 101, 100, 99, 98, 97, 99, 100])
    rsi = rsi_series(prices, 14, wilder=True)
    gains, losses = prices.diff().clip(lower=0).iloc[1:15].mean(), -prices.diff().clip(upper=0).iloc[1:15].mean()
    assert rsi.iloc[14] == pytest.approx(100 - 100 / (1 + gains / losses))
    assert rsi.iloc[15] == pytest.approx(100 - 100 / (1 + ((gains * 13 + 1) / 14) / (losses * 13 / 14)))
    delta = prices.diff()
    expected = (
        100 - 100 / (1 + delta.where(delta > 0, 0).rolling(14).mean() / -delta.where(delta < 0, 0).rolling(14).mean())
    ).fillna(50)
    pd.testing.assert_series_equal(rsi_series(prices), expected)


def test_raw_features_oversold_and_normal_decline():
    bars = history(falling())
    features = calculate_features(bars)
    row = evaluate(bars)
    assert row["mr_state"] == "MR_OVERSOLD"
    assert row["rsi14"] <= 35
    assert row["distance_from_ma20_atr"] == pytest.approx((88 - features["ma20"]) / features["atr20"])
    assert features["return_3d"] == pytest.approx(88 / 97 - 1)
    assert features["return_5d"] == pytest.approx(88 / 100.2 - 1)
    assert evaluate(history([100 - i * 0.01 for i in range(60)]))["mr_state"] == "MR_NONE"


def test_oversold_then_rebound_edge_and_continued_falling():
    prices = falling()
    assert evaluate(history(prices + [85]))["mr_state"] != "MR_REBOUND"
    states = [evaluate(history(prices + [89, 90, 91][:i]))["mr_state"] for i in range(1, 4)]
    assert states[0] == "MR_REBOUND"
    assert states.count("MR_REBOUND") == 1
    bad_clv = history(prices + [89])
    bad_clv[-1] = replace(bad_clv[-1], high=95)
    assert evaluate(bad_clv)["mr_state"] != "MR_REBOUND"


def test_future_append_and_preview_cannot_change_historical_state():
    bars = history(falling() + [89])
    original = evaluate(bars)
    appended = bars + history([200])
    assert evaluate(appended[: len(bars)]) == original
    preview_features = calculate_features(bars, preview=True)
    assert calculate_mean_reversion(bars, preview_features) == original


def test_official_consumed_episode_prevents_replay_reset():
    bars = history(falling() + [89])
    row = evaluate(bars, previous_features={"mr_state": "MR_OVERSOLD", "mr_episode_consumed": True, "rsi14": 5})
    assert row["mr_state"] != "MR_REBOUND"


def test_mean_reversion_does_not_mutate_alpha_entry_candidate_or_state():
    from copy import deepcopy
    from finance_analysis.trend_following.entry import calculate_entry
    from finance_analysis.trend_following.ranking import rank_candidates
    from finance_analysis.trend_following.state import transition_state

    bars = history(falling() + [89])
    original = calculate_features(bars)
    original.update(code="AAA.US", rs_5d=-0.1, rs_10d=-0.2, rs_20d=-0.1)
    enriched = {**deepcopy(original), **calculate_mean_reversion(bars, original)}
    original, enriched = rank_candidates([original])[0], rank_candidates([enriched])[0]
    for key in ("alpha_score", "trend_score", "rs_score", "setup_score", "path_score", "is_candidate"):
        assert original[key] == enriched[key]
    assert calculate_entry(original) == calculate_entry(enriched)
    assert transition_state(original, None) == transition_state(enriched, None)


def test_new_oversold_episode_can_rearm_after_leaving_oversold():
    bars = history(falling() + [89])
    first = evaluate(bars)
    assert first['mr_state'] == 'MR_REBOUND'
    bars = history(falling() + [89, 105])
    exited = evaluate(bars, previous_features=first)
    assert exited['mr_state'] == 'MR_NONE'
    assert exited['mr_episode_consumed'] is False
    bars = history(falling() + [89, 105, 80])
    oversold = evaluate(bars, previous_features=exited)
    assert oversold['mr_state'] == 'MR_OVERSOLD'
    bars = history(falling() + [89, 105, 80, 81])
    second = evaluate(bars, previous_features=oversold)
    assert second['mr_state'] == 'MR_REBOUND'
