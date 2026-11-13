import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.intraday_options.scoring import calculate, combine

START = datetime(2026, 11, 12, 14, 30, tzinfo=timezone.utc)


def candles(steps, symbol="SPY.US", start=START, base=100):
    bars = []
    price = float(base)
    for i, step in enumerate(steps):
        close = price * math.exp(step)
        when = start + timedelta(minutes=i)
        bars.append(
            CandleState(
                symbol,
                when,
                Decimal(str(price)),
                Decimal(str(max(price, close) * math.exp(0.0001))),
                Decimal(str(min(price, close) * math.exp(-0.0001))),
                Decimal(str(close)),
                1000,
                None,
                "regular",
                True,
                when + timedelta(minutes=1),
            )
        )
        price = close
    return bars


def score(bars):
    return calculate(bars[0].symbol, bars, max(b.bar_time for b in bars) + timedelta(minutes=1))


def test_up_down_are_symmetric_and_independent_of_price_level():
    up = score(candles([0.0004] * 60))
    down = score(candles([-0.0004] * 60))
    expensive = score(candles([0.0004] * 60, base=10000))
    assert up["direction"] == "bullish" and down["direction"] == "bearish"
    assert up["score"] > 85
    assert up["score"] == pytest.approx(down["score"], abs=0.01)
    assert up["score"] == pytest.approx(expensive["score"], abs=0.01)
    for w in down["windows"]:
        assert w["return_pct"] < 0 and w["direction"] == -1
        assert 0 <= w["score"] <= 100


def test_flat_tiny_moves_and_chop_are_not_high_quality():
    for steps in ([0] * 60, [0.0000001] * 60, [0.003, -0.003] * 30):
        result = score(candles(steps))
        assert result["score"] < 20
        assert result["direction"] == "neutral"
        assert result["state"] == "waiting"


def test_single_impulse_then_stall_is_capped_and_explained():
    result = score(candles([0.02] + [0] * 59))
    long = result["windows"][-1]
    assert long["efficiency"] == pytest.approx(100)
    assert long["stalled_impulse"] and long["score"] <= 35
    assert any("单根" in reason for reason in long["reasons"])
    assert result["score"] < 35


def test_partial_opening_windows_score_only_closed_same_session_minutes():
    bars = candles([0.0004] * 60)
    for count in (1, 2, 4, 5, 14, 15, 29, 30, 59, 60):
        result = score(bars[:count])
        assert (result["score"] is not None) == (count >= 2)
        assert [w["score"] is not None for w in result["windows"]] == [count >= 2] * 4
        for window in result["windows"]:
            assert window["available_bars"] == min(count, window["minutes"])
            assert window["missing_bars"] == max(0, window["minutes"] - count)
            assert window["data_status"] == ("warming" if count < window["minutes"] else "ready")
    gap = score(bars[:35] + bars[36:])
    assert [w["data_status"] for w in gap["windows"]] == ["ready", "ready", "gap", "gap"]
    assert gap["score"] is not None
    assert gap["windows"][-1]["missing_bars"] == 1
    yesterday = candles([0.0004] * 60, start=START - timedelta(days=1))
    assert score(yesterday + bars[:14]) == score(bars[:14])
    preview = replace(bars[59], confirmed=False)
    preview_result = calculate("SPY.US", bars[:59] + [preview], START + timedelta(minutes=60))
    assert preview_result["as_of"] == (START + timedelta(minutes=59)).isoformat()
    assert preview_result["windows"][-1]["missing_bars"] == 1
    assert preview_result["score"] == score(bars[:59])["score"]
    future = calculate("SPY.US", bars, START + timedelta(minutes=30))
    assert future["as_of"] == (START + timedelta(minutes=30)).isoformat()
    assert future["score"] == score(bars[:30])["score"]


@pytest.mark.parametrize("field,value", [("partial", True), ("sampled", True), ("close", Decimal("0"))])
def test_bad_minutes_are_not_filled(field, value):
    bars = candles([0.0004] * 60)
    bars[55] = replace(bars[55], **{field: value})
    result = score(bars)
    assert result["score"] is not None
    assert all(w["data_status"] == "gap" for w in result["windows"])


def test_afterhours_and_early_close_are_excluded():
    # Thanksgiving Friday closes at 13:00 NY / 18:00 UTC.
    start = datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc)
    bars = candles([0.0004] * 240, start=start)
    result = score(bars)
    assert result["as_of"] == "2026-11-27T18:00:00+00:00"
    assert result["windows"][-1]["start_at"] == "2026-11-27T17:00:00+00:00"


def test_alignment_direction_and_state_are_separate():
    bars = candles([0.0003] * 60)
    windows = score(bars)["windows"][1:]
    same = combine(windows, bars)
    pullback = combine([{**windows[0], "direction": -1}, *windows[1:]], bars)
    conflict = combine([{**windows[0], "direction": -1}, {**windows[1], "direction": -1}, windows[2]], bars)
    assert same["alignment"] == 1
    assert pullback["direction"] == "bullish" and pullback["state"] == "pullback"
    assert pullback["score"] < same["score"] and pullback["score"] <= 65
    assert conflict["direction"] == "conflict" and conflict["state"] == "conflict"
    assert conflict["score"] <= 55
    assert combine([{**w, "direction": 0} for w in windows], bars)["score"] <= 35


def test_sparse_windows_use_real_time_and_require_two_valid_bars():
    bars = candles([0.0004] * 60)
    sparse = score([bars[0], bars[20], bars[59]])
    assert sparse["score"] is not None  # usable long window alone still contributes
    assert sparse["base_score"] == sparse["windows"][-1]["score"]
    assert sparse["alignment"] == abs(sparse["windows"][-1]["direction"])
    assert "归一化权重" in sparse["explanation"]
    long = sparse["windows"][-1]
    assert long["score"] is not None and long["missing_bars"] == 57
    assert long["stability"] == pytest.approx(100)
    assert "仅供参考" in sparse["explanation"]
    gap = score(bars[:45] + bars[46:])
    assert gap["score"] is not None
    assert gap["windows"][1]["available_bars"] == 14
    assert gap["windows"][1]["start_at"] == bars[46].bar_time.isoformat()


def test_five_minute_window_is_independent_of_composite_and_detects_stall():
    bars = candles([0.0004] * 60)
    result = score(bars)
    assert result["windows"][0]["minutes"] == 5
    assert result["windows"][0]["start_at"] == bars[-5].bar_time.isoformat()
    assert result["windows"][0]["score"] > 0
    windows = result["windows"]
    baseline = combine(windows[1:], bars)
    assert combine(windows, bars) == baseline
    assert combine([{**windows[0], "score": None, "direction": -1}, *windows[1:]], bars) == baseline
    impulse = score(candles([0.02, 0, 0, 0, 0]))["windows"][0]
    assert impulse["stalled_impulse"] and impulse["score"] <= 35
    assert "最近2分钟" in impulse["reasons"][0]


def test_sparse_recent_bars_do_not_break_extension_check():
    bars = candles([0.0004] * 60)
    sparse = bars[:40] + [bars[40], bars[45], bars[50], bars[59]]
    result = score(sparse)
    assert result["score"] is not None
    assert result["windows"][0]["score"] is None


def test_opening_with_gaps_keeps_reference_scores_and_no_fabricated_bars():
    bars = candles([0.0004] * 10)
    result = score(bars[:3] + bars[5:])
    long = result["windows"][-1]
    assert long["data_status"] == "gap"
    assert long["available_bars"] == 8 and long["missing_bars"] == 52
    assert any("开盘仅10分钟" in reason for reason in long["reasons"])
    assert any("缺少2根" in reason for reason in long["reasons"])
    assert result["score"] is not None and "仅供参考" in result["explanation"]
    # A single valid candle and all-invalid observations cannot fabricate a score.
    assert score([bars[-1]])["score"] is None
    assert score([replace(b, sampled=True) for b in bars])["score"] is None


def test_opening_window_uses_elapsed_time_scale_without_changing_full_windows():
    result = score(candles([0.0004] * 5))
    assert len({w["score"] for w in result["windows"]}) == 1
    assert len({w["normalized_move"] for w in result["windows"]}) == 1
    assert result["windows"][-1]["minutes"] == 60
    assert result["windows"][-1]["missing_bars"] == 55


def test_composite_renormalizes_available_windows_and_does_not_treat_missing_as_neutral():
    bars = candles([0.0004] * 60)
    windows = score(bars)["windows"][1:]
    mixed = [{**windows[0], "score": 80, "direction": 1},
             {**windows[1], "score": None}, {**windows[2], "score": 40, "direction": -1}]
    result = combine(mixed, bars)
    assert result["base_score"] == pytest.approx((80 * .30 + 40 * .25) / .55, abs=.01)
    assert result["alignment"] == pytest.approx(.05 / .55)
    assert result["direction"] == "conflict"
    assert result["state"] == "conflict"
    only_long = combine([{**w, "score": None} for w in windows[:2]] + [windows[2]], bars)
    assert only_long["score"] == windows[2]["score"]
    assert only_long["direction"] == "bullish"


@pytest.mark.parametrize("direction", [1, -1])
def test_missing_window_does_not_override_observed_neutral_direction(direction):
    bars = candles([0.0004] * 60)
    windows = score(bars)["windows"][1:]
    mixed = [{**windows[0], "score": None},
             {**windows[1], "direction": 0}, {**windows[2], "direction": direction}]
    result = combine(mixed, bars)
    assert result["direction"] == "neutral"
    assert result["state"] == "waiting"
    assert result["score"] <= 35
