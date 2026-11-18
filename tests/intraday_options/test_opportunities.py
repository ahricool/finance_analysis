"""Entry process tests use causal price paths, not pre-labelled structures."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from finance_analysis.interfaces.api.v1.schemas.intraday_options import TrendResult
from tests.intraday_options.test_scoring import candles, score
from tests.intraday_options.test_structure import oscillation, prices


def entry(values):
    result = score(prices(values))
    TrendResult.model_validate(result)
    return result["opportunities"]


def branch(result, kind):
    return next(b for b in result["branches"] if b["kind"] == kind)


@pytest.mark.parametrize("side", [1, -1])
def test_breakout_confirmation_extension_failure_and_fixed_identity(side):
    def run(tail):
        return entry([100 + side * (p - 100) for p in oscillation() + tail])

    forming = run([101.3])
    assert branch(forming, "box_breakout")["confirmed_at"] is None
    first = run([101.3, 101.4])
    primary = first["primary"]
    assert primary["kind"] == "box_breakout"
    assert primary["direction"] == ("bullish" if side == 1 else "bearish")
    assert 0 <= primary["quality_score"] <= 100
    extended = branch(run([101.3, 101.4, 103]), "box_breakout")
    assert extended["status"] == "extended"
    assert extended["structure_id"] == primary["structure_id"]
    assert extended["trigger"] == primary["trigger"]
    assert extended["atr"] == primary["atr"]
    assert extended["confirmed_at"] == primary["confirmed_at"]
    assert branch(run([101.3, 101.4, 103]), "box_breakout")["status"] == "extended"
    failed = run([101.3, 101.4, 100, 102, 102.1])
    assert branch(failed, "box_breakout")["status"] == "invalidated"
    assert not any(b["kind"] == "box_breakout" and b["status"] == "confirmed" for b in failed["branches"])


@pytest.mark.parametrize("side", [1, -1])
def test_retest_needs_post_breakout_touch_and_two_closes(side):
    def run(tail):
        return entry([100 + side * (p - 100) for p in oscillation() + tail])

    assert not any(b["kind"] == "box_retest" for b in run([101.3, 101.4])["branches"])
    touch = run([101.3, 101.4, 101.15, 101.4])
    assert branch(touch, "box_retest")["status"] == "forming"
    result = run([101.3, 101.4, 101.15, 101.4, 101.45])
    retest = branch(result, "box_retest")
    assert retest["status"] == "confirmed"
    assert retest["confirmed_at"] > branch(result, "box_breakout")["confirmed_at"]
    assert retest["trigger"] == branch(result, "box_breakout")["trigger"]
    assert result["primary"]["quality_score"] == max(
        b["quality_score"] for b in result["branches"] if b["status"] == "confirmed"
    )


@pytest.mark.parametrize("side", [1, -1])
def test_trend_recovery_requires_prior_advance_then_touch_and_actual_recovery(side):
    base = [100 + i * 0.1 for i in range(40)]

    def run(tail):
        return entry([100 + side * (p - 100) for p in base + tail])

    assert run([])["primary"] is None  # Strong monotone trend is not itself an entry.
    touched = run([103.05])
    assert branch(touched, "trend_recovery")["status"] == "forming"
    assert touched["primary"] is None
    result = run([103.05, 103.1, 103.15, 103.2, 103.3])
    assert result["primary"]["kind"] == "trend_recovery"
    assert result["primary"]["trigger"] == branch(touched, "trend_recovery")["trigger"]
    failed = run([103.05, 102.5, 103.1, 103.2, 103.3])
    assert branch(failed, "trend_recovery")["status"] == "invalidated"
    assert failed["primary"] is None


@pytest.mark.parametrize("change", ["partial", "sampled", "invalid"])
def test_incomplete_data_cannot_supply_primary(change):
    bars = prices(oscillation() + [101.3, 101.4])
    bars[-5] = replace(bars[-5], **({"close": Decimal(0)} if change == "invalid" else {change: True}))
    result = score(bars)["opportunities"]
    assert result["reference"] and result["missing_bars"] == 1
    assert result["primary"] is None


def test_gap_between_confirmation_candles_and_future_data():
    bars = prices(oscillation() + [101.3, 101.4, 101.5])
    assert score(bars[:41] + bars[42:])["opportunities"]["primary"] is None
    from finance_analysis.intraday_options.scoring import calculate

    now = bars[-2].bar_time + timedelta(minutes=1)
    expected = calculate("SPY.US", bars[:-1], now)["opportunities"]
    assert calculate("SPY.US", bars, now)["opportunities"] == expected
    assert calculate("SPY.US", bars[:-1] + [replace(bars[-1], confirmed=False)], now)["opportunities"] == expected


def test_expiry_no_trend_score_regression_and_opening_warmup():
    result = entry(oscillation() + [101.3, 101.4] + [101.4] * 14)
    assert branch(result, "box_breakout")["status"] == "expired"
    assert result["primary"] is None
    trend = score(candles([0.0004] * 60))
    assert trend["score"] > 85 and trend["opportunities"]["primary"] is None
    assert entry(oscillation(14))["reference"]
    assert not entry(oscillation(15))["reference"]


def test_price_scale_invariance_and_replay_determinism():
    values = oscillation() + [101.3, 101.4]
    bars = prices(values)
    scaled = [
        replace(b, **{field: getattr(b, field) * 100 for field in ("open", "high", "low", "close")}) for b in bars
    ]
    a, b = score(bars)["opportunities"], score(scaled)["opportunities"]
    assert a["primary"]["quality_score"] == pytest.approx(b["primary"]["quality_score"])
    assert a == score(bars)["opportunities"]


def test_rolling_replay_preserves_process_levels_dates_and_first_confirmation():
    values = oscillation() + [101.3, 101.4, 101.15, 101.4, 101.45] + [101.45] * 30
    fixed, confirmations = {}, {}
    for end in range(31, len(values) + 1):
        for item in entry(values[:end])["branches"]:
            identity = item["structure_id"]
            evidence = tuple(item[k] for k in ("trigger", "invalidation", "atr", "started_at", "expires_at"))
            assert fixed.setdefault(identity, evidence) == evidence
            if item["confirmed_at"]:
                assert confirmations.setdefault(identity, item["confirmed_at"]) == item["confirmed_at"]


def test_retest_uses_original_formation_and_never_extends_parent_expiry():
    result = entry(oscillation() + [101.3, 101.4, 101.15, 101.4, 101.45])
    original, retest = branch(result, "box_breakout"), branch(result, "box_retest")
    assert retest["formation_start"] == original["formation_start"]
    assert retest["expires_at"] == original["expires_at"]


def test_shared_morning_gaps_are_filled_after_real_minutes_resume():
    """V2 marks flat assumptions instead of waiting an hour for old gaps to leave."""
    from finance_analysis.intraday_options.opportunities import calculate_opportunities

    bars = candles([0.0001] * 142)
    # Offsets from 09:30: 09:59–10:04, 10:07–10:12, 10:18–10:19, 10:47–10:51.
    missing = set(range(29, 35)) | set(range(37, 43)) | {48, 49} | set(range(77, 82))
    available = [b for i, b in enumerate(bars) if i not in missing]
    resumed = calculate_opportunities([b for b in available if b.bar_time <= bars[82].bar_time])
    assert not resumed["reference"]
    assert resumed["filled_bars"] == 19
    assert resumed["recent_available_bars"] == 15
    assert not calculate_opportunities(available)["reference"]
    assert calculate_opportunities(available)["missing_bars"] == 0
