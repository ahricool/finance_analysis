"""Business invariants for causal opportunity selection and frozen evidence."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.opportunities import (
    build_opportunities,
    confirmed_pivots,
    detect_patterns,
    select_primary,
    VERSION,
)


def bars(values, volumes=None):
    return [
        DailyBar(date(2025, 1, 1) + timedelta(days=i), v - 0.1, v + 0.5, v - 0.5, v, volumes[i] if volumes else 1000)
        for i, v in enumerate(values)
    ]


def platform():
    values = [70 + i * 0.5 for i in range(65)] + [103 + (i % 6) * 0.3 for i in range(35)]
    result = bars(values + [105.6], [1000] * 100 + [1800])
    result[-1] = replace(result[-1], high=105.7)
    return result


def branch(kind, status, score, **extra):
    return dict(kind=kind, status=status, quality_score=score, structure_id=kind, **extra)


def test_primary_never_borrows_invalid_or_extended_quality():
    records = [
        branch("vcp", "INVALIDATED", 99, trigger=100),
        branch("box", "EXTENDED", 98),
        branch("ma10", "CONFIRMED", 60, trigger=80),
    ]
    assert select_primary(records) is records[2]
    assert select_primary(records[:2]) is None


def test_platform_prior_advance_and_known_boundary():
    history = platform()
    detected = detect_patterns(history)
    flat = next(b for b in detected if b["kind"] == "flat_base")
    assert flat["trigger"] == max(b.high for b in history[-flat["evidence"]["window"] - 1 : -1])
    assert flat["end_date"] < history[-1].trade_date.isoformat()
    changed = history[:-1] + [replace(history[-1], high=999)]
    assert detect_patterns(changed) == detected
    no_advance = [replace(b, open=103, high=104, low=102, close=103) for b in history[:65]] + history[65:]
    assert not any(b["kind"] == "flat_base" for b in detect_patterns(no_advance))


def test_frozen_boundary_dedup_preview_and_rebase():
    history = platform()
    first = build_opportunities("A.US", history, {})
    assert first["primary"] is not None
    assert "flat_base" in first["events"]
    frozen = deepcopy(first)
    next_bar = replace(history[-1], trade_date=history[-1].trade_date + timedelta(days=1), high=106)
    second = build_opportunities("A.US", history + [next_bar], {}, first)
    assert not second["events"]
    assert second["primary"]["first_confirmed_at"] == first["primary"]["first_confirmed_at"]
    preview = build_opportunities("A.US", history, {}, preview=True)
    assert not preview["events"] and preview["primary"] is None
    assert first == frozen
    adjusted = [
        replace(b, open=b.open / 2, high=b.high / 2, low=b.low / 2, close=b.close / 2) for b in history + [next_bar]
    ]
    rebased = build_opportunities("A.US", adjusted, {}, first)
    assert rebased["primary"]["trigger"] == pytest.approx(first["primary"]["trigger"] / 2)
    assert rebased["primary"]["structure_id"] == first["primary"]["structure_id"]
    assert not rebased["events"]


def test_insufficient_missing_and_bad_ohlc_are_not_negative_patterns():
    history = platform()
    assert build_opportunities("A.US", history[:10], {})["history_status"] == "insufficient"
    assert (
        build_opportunities("A.US", history[:-2] + history[-1:], {}, sessions=[b.trade_date for b in history])[
            "history_status"
        ]
        == "missing_sessions"
    )
    bad = history[:-1] + [replace(history[-1], low=200)]
    assert build_opportunities("A.US", bad, {})["history_status"] == "invalid_ohlc"
    missing_volume = [replace(b, volume=None) for b in history]
    assert not build_opportunities("A.US", missing_volume, {})["primary"]


def test_pivots_are_known_only_after_right_confirmation_and_never_backdated():
    history = bars([100, 102, 105, 102, 100, 101, 103])
    assert not confirmed_pivots(history[:4])
    pivot = confirmed_pivots(history[:5])[0]
    assert pivot["date"] == history[2].trade_date.isoformat()
    assert pivot["known_date"] == history[4].trade_date.isoformat()
    assert pivot in confirmed_pivots(history)


def interpolate(points):
    result = []
    for (x, y), (end, target) in zip(points, points[1:]):
        result.extend(y + (target - y) * (i - x) / (end - x) for i in range(x, end))
    return result + [points[-1][1]]


def test_cup_handle_accepts_rounded_base_and_rejects_sharp_v():
    prefix = [60 + i * 0.5 for i in range(80)]
    cup = interpolate([(0, 110), (5, 120), (30, 102), (45, 100), (60, 103), (85, 119), (90, 114), (99, 118)])
    history = bars(prefix + cup + [121])
    patterns = detect_patterns(history)
    assert any(p["kind"] == "cup_handle" for p in patterns)
    sharp = interpolate([(0, 110), (5, 120), (44, 118), (45, 100), (46, 118), (85, 119), (90, 114), (99, 118)])
    assert not any(p["kind"] == "cup_handle" for p in detect_patterns(bars(prefix + sharp + [121])))


def test_vcp_requires_actual_decreasing_swings_and_volume_for_confirmation():
    prefix = [60 + i for i in range(60)]
    vcp = interpolate([(0, 121), (5, 130), (20, 110), (35, 128), (45, 115), (58, 126), (65, 120), (79, 124)])
    history = bars(prefix + vcp + [127])
    detected = detect_patterns(history)
    assert any(p["kind"] == "vcp" for p in detected)
    assert not any(p["kind"] == "vcp" for p in detect_patterns(bars([100 + i * 0.1 for i in range(141)])))
    # Constant volume is not dry-up evidence, even with a large final volume.
    history[-1] = replace(history[-1], volume=2000)
    result = build_opportunities("A.US", history, {})
    vcp_record = next(b for b in result["branches"] if b["kind"] == "vcp")
    assert vcp_record["status"] != "CONFIRMED" and vcp_record["unmet"]


def test_entry_events_use_branch_confirmation_not_legacy_resume():
    history = platform()
    entry = {
        "entry_breakdown": {
            "pullbacks": {
                "ma5": dict(
                    status="CONFIRMED",
                    quality_score=60,
                    evidence={"support": 105, "touch_date": history[-1].trade_date.isoformat()},
                    checks={"recovery": True},
                )
            }
        }
    }
    first = build_opportunities("A.US", history, entry)
    assert "ma5" in first["events"]
    second = build_opportunities("A.US", history, entry, first)
    assert "ma5" not in second["events"]
    assert first["version"] == VERSION


def test_cross_period_union_keeps_one_structure_and_valid_branch_quality():
    from finance_analysis.trend_following.opportunities import opportunity_items

    valid = branch("ma5", "CONFIRMED", 60, background_periods=[10])
    invalid = branch("ma5", "INVALIDATED", 99, background_periods=[40])
    result = opportunity_items(
        [dict(code="A.US", features={"opportunities": {"branches": [b]}}) for b in (invalid, valid)]
    )
    assert len(result) == 1 and len(result[0]["branches"]) == 1
    assert result[0]["primary"]["quality_score"] == 60
    assert result[0]["primary"]["background_periods"] == [10, 40]


def test_expired_structure_cannot_rearm_through_an_overlapping_rolling_window():
    history = platform()
    first = build_opportunities("A.US", history, {})
    b = next(b for b in first["branches"] if b["kind"] == "flat_base")
    b["status"] = "INVALIDATED"
    second = build_opportunities("A.US", history, {}, first)
    b2 = next(b for b in second["branches"] if b["kind"] == "flat_base")
    assert b2["status"] == "INVALIDATED"
    assert not b2["fresh"] and b2["first_confirmed_at"] == b["first_confirmed_at"]


def test_read_api_uses_saved_union_and_checks_preview_date(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import trend_following as api

    history = platform()
    document = build_opportunities("A.US", history, {})
    day = history[-1].trade_date
    rows = [dict(code="A.US", name="A", features={"opportunities": document}, generated_at=None)]
    repo = SimpleNamespace(latest_trade_date=lambda: day, opportunity_rows=lambda _: rows)
    monkeypatch.setattr(api, "TrendFollowingRepository", lambda **kw: repo)
    monkeypatch.setattr(
        api, "load_preview", lambda *args, **kw: dict(trade_date=str(day), snapshots=rows, preview_time=None)
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app)
    response = client.get("/opportunities?market=US")
    assert response.status_code == 200
    assert response.json()["items"][0]["primary"]["trigger"] == document["primary"]["trigger"]
    assert client.get("/opportunities?market=US&mode=preview&trade_date=2020-01-01").status_code == 404


def test_twenty_day_box_does_not_require_sixty_day_shape_history():
    from tests.test_trend_following_box import box_bars

    prefix = bars([70 + i * 1.4 for i in range(21)])
    box = box_bars(days=20, close=105)
    history = prefix + [replace(b, trade_date=prefix[-1].trade_date + timedelta(days=i + 1)) for i, b in enumerate(box)]
    history[-1] = replace(history[-1], volume=1800)
    candidate = next(b for b in detect_patterns(history) if b["kind"] == "box")
    assert candidate["evidence"]["box_window_days"] == 20
    result = build_opportunities("A.US", history, {})
    assert next(b for b in result["branches"] if b["kind"] == "box")["status"] == "CONFIRMED"
