"""Formal downstream eligibility, deduplication and score boundaries."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from finance_analysis.trend_following.opportunity_inputs import formal_opportunities
from finance_analysis.confluence.v2 import evaluate

DAY = "2026-09-18"


def document(**branch_changes):
    branch = dict(
        kind="ma10",
        status="CONFIRMED",
        quality_score=82,
        structure_id="stable",
        rule_version="ohlcv_opportunity_v1",
        trigger=100,
        support=99,
        invalidation=95,
        first_confirmed_at=DAY,
        data_as_of=DAY,
        preview=False,
        anchor_date=DAY,
        anchor_close=101,
        price_basis="forward_adjusted",
    )
    branch.update(branch_changes)
    return dict(
        version="ohlcv_opportunity_v1", history_status="complete", preview=False, data_as_of=DAY, branches=[branch]
    )


def row(period=10, **branch_changes):
    return dict(
        code="T1.US",
        trade_date=DAY,
        trend_period=period,
        generated_at="2026-09-18T22:00:00+00:00",
        state="WATCHING",
        alpha_score=50,
        features=dict(opportunities=document(**branch_changes)),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "EXTENDED"},
        {"status": "INVALIDATED"},
        {"status": "NEAR_TRIGGER"},
        {"preview": True},
        {"rule_version": "future"},
        {"data_as_of": "2026-09-17"},
        {"first_confirmed_at": "2026-09-21"},
        {"first_confirmed_at": None},
        {"quality_score": float("nan")},
        {"quality_score": True},
        {"quality_score": 101},
        {"trigger": 0},
        {"invalidation": None},
        {"structure_id": ""},
    ],
)
def test_invalid_branch_is_not_an_opportunity(changes):
    item = formal_opportunities([row(**changes)], DAY)[0]
    assert item["primary"] is None
    assert item["branches"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "old"),
        ("preview", True),
        ("data_as_of", "2026-09-17"),
        ("history_status", "invalid_ohlc"),
        ("history_status", "missing_sessions"),
    ],
)
def test_unavailable_document_is_distinct_from_evaluated_empty(field, value):
    source = row()
    source["features"]["opportunities"][field] = value
    assert formal_opportunities([source], DAY) == []


def test_period_deduplication_chooses_intact_best_record_without_mutating_input():
    rows = [row(40, quality_score=90, trigger=105), row(10), row(20)]
    frozen = deepcopy(rows)
    a = formal_opportunities(rows, DAY)
    assert a == formal_opportunities(list(reversed(rows)), DAY)
    assert rows == frozen
    assert len(a[0]["branches"]) == 1
    assert a[0]["primary"]["background_periods"] == [10, 20, 40]
    assert a[0]["primary"]["quality_score"] == 90
    assert a[0]["primary"]["trigger"] == 105


def test_exact_snapshot_date_and_exclusive_freeze_cutoff():
    source = row()
    cutoff = datetime(2026, 9, 18, 22, tzinfo=timezone.utc)
    assert formal_opportunities([source], DAY, cutoff) == []
    assert formal_opportunities([source], "2026-09-21") == []
    source["generated_at"] = "2026-09-18T21:59:59+00:00"
    assert formal_opportunities([source], DAY, cutoff)[0]["primary"]


def test_new_opportunity_is_one_alternative_route_not_three_votes():
    facts = dict(trade_date=DAY, periods=[row(10), row(20), row(40)])
    result = evaluate("trend", facts)
    assert result["strength"] == 82
    assert result["weight"] == 30
    assert len(result["evidence"]["opportunities"]) == 1
    assert result["evidence"]["background_strength"] == 50
    assert result["evidence"]["dominant_route"] == "opportunity"


def test_inactive_new_entry_does_not_leak_through_legacy_breakout_score():
    source = row(status="EXTENDED")
    source["features"].update(entry_type="BREAKOUT", entry_score=99, box_state="BOX_BREAKOUT", box_quality=98)
    result = evaluate("trend", dict(trade_date=DAY, periods=[source]))
    assert result["strength"] == 50
    assert result["evidence"]["opportunity_strength"] == 0
    del source["features"]["opportunities"]
    assert evaluate("trend", dict(trade_date=DAY, periods=[source]))["strength"] == 99


def test_corrupt_new_document_cannot_restore_old_breakout_route():
    source = row()
    source["features"]["opportunities"]["history_status"] = "invalid_ohlc"
    source["features"].update(entry_type="BREAKOUT", entry_score=99)
    result = evaluate("trend", dict(trade_date=DAY, periods=[source]))
    assert result["strength"] == 50
    assert result["evidence"]["opportunity_strength"] is None


def test_malformed_or_wrong_security_document_is_unavailable():
    source = row()
    source["features"]["opportunities"]["branches"] = None
    assert formal_opportunities([source], DAY) == []
    source = row()
    source["features"]["opportunities"]["code"] = "OTHER.US"
    assert formal_opportunities([source], DAY) == []


def test_intraday_evaluation_cannot_replace_frozen_buy_point_evidence():
    from finance_analysis.database.repositories.intraday_confirmation_store import merge_evidence
    frozen = dict(status="frozen", generated_at=None, items=[dict(
        code="T1.US", candidate_sources=["opportunities"],
        source_evidence=[dict(source="opportunities", opportunities=[row()["features"]["opportunities"]["branches"][0]])],
    )])
    changed = deepcopy(frozen)
    changed["status"] = "evaluated"
    changed["items"][0]["source_evidence"][0]["opportunities"][0]["trigger"] = 999
    changed["items"][0]["candidate_sources"] = ["trend"]
    saved = merge_evidence(frozen, changed)
    assert saved["items"][0]["source_evidence"] == frozen["items"][0]["source_evidence"]
    assert saved["items"][0]["candidate_sources"] == ["opportunities"]
