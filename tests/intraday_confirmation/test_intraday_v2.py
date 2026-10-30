"""V2 business regressions: full session, auxiliary volume/trend and current vs historical status."""

from copy import deepcopy
from datetime import timedelta

import pytest
from test_confirmation import OPEN, SESSION, bar, quote, history, inputs, Store
from finance_analysis.intraday_confirmation import config
from finance_analysis.intraday_confirmation.engine import metrics, decision, stabilize
from finance_analysis.intraday_confirmation.service import ConfirmationService


def test_negative_opening_15m_does_not_veto_later_recovery():
    now = OPEN + timedelta(minutes=60)
    bars = [
        bar(
            OPEN + timedelta(minutes=i), close=99.5 if i < 15 else 102, low=99, high=101 if i < 15 else 103, volume=None
        )
        for i in range(60)
    ]
    m = metrics(quote(now), bars, quote(now, price=100), history(), SESSION, now)
    assert m["return_15m"] < 0
    assert m["minute_count"] == 60 and m["session_complete"]
    assert m["session_mean_price"] == pytest.approx(sum((b.high + b.low + b.close) / 3 for b in bars) / 60)
    result = decision(m, {"impact": "unavailable"})  # ETFs have no formal Trend.
    assert result["proposed_state"] == "CONFIRMED"
    assert result["score_breakdown"]["volume_score"] is None
    assert result["available_score_weight"] == 85


def test_volume_never_gates_confirmation_and_has_only_five_points():
    m = inputs()
    results = [decision({**m, "volume_ratio": v}, {"impact": "intact"}) for v in (0, 0.1, 10000, None)]
    assert {r["proposed_state"] for r in results} == {"CONFIRMED"}
    assert config.SCORE_WEIGHTS["volume"] == 5
    assert results[2]["confirmation_score"] - results[0]["confirmation_score"] == 5


def test_missing_middle_minute_cannot_advance_or_disguise_partial_session():
    now = OPEN + timedelta(minutes=30)
    bars = [bar(OPEN + timedelta(minutes=i)) for i in range(30) if i != 17]
    m = metrics(quote(now), bars, quote(now, price=100), history(), SESSION, now)
    assert m["minute_count"] == 29 and m["expected_minute_count"] == 30
    assert not m["data_fresh"] and m["session_mean_price"] is None
    r = decision(m, {"impact": "intact"})
    assert r["proposed_state"] == "WAIT" and r["data_status"] == "UNAVAILABLE"
    assert r["confirmation_score"] is None


def test_current_state_can_weaken_or_expire_without_erasing_confirmation():
    now = OPEN + timedelta(minutes=20)
    old = {"state": "CONFIRMED", "first_confirmed_at": now.isoformat(), "first_confirmed_price": 102}
    active = stabilize(decision(inputs(), {}), old, now, now)
    assert active["current_status"] == "ACTIVE"
    m = {**inputs(), "break_above_opening_range": False}
    weak = stabilize(decision(m, {}), active, now + timedelta(minutes=5), now + timedelta(minutes=5))
    assert weak["state"] == "CONFIRMED" and weak["current_status"] == "WEAKENING"
    outage = stabilize(decision({**m, "data_fresh": False}, {}), weak, None, now + timedelta(minutes=10))
    assert outage["current_status"] == "UNAVAILABLE" and outage["state"] == "CONFIRMED"
    assert outage["first_confirmed_at"] == old["first_confirmed_at"]


def test_long_gap_cannot_satisfy_two_observations():
    now = OPEN + timedelta(minutes=15)
    first = stabilize(decision(inputs(), {}), {}, now, now)
    later = now + timedelta(minutes=11)
    second = stabilize(decision(inputs(), {}), first, later, later)
    assert second["state"] == "WAIT" and second["pending_count"] == 1


def test_read_projects_expired_current_state_and_multisource_filter_without_write(monkeypatch):
    store = Store()
    store.value = dict(
        rule_version=config.RULE_VERSION,
        items=[
            dict(
                code="ABC.US",
                state="CONFIRMED",
                current_status="ACTIVE",
                first_confirmed_at=OPEN.isoformat(),
                candidate_source="confluence",
                candidate_sources=["confluence", "trend"],
                metrics={"quote_time": (OPEN + timedelta(minutes=10)).isoformat()},
                confirmation_score=99,
                chase_risk="LOW",
            )
        ],
    )
    original = deepcopy(store.value)
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.resolve_session", lambda *a: SESSION)
    result = ConfirmationService(store=store).read("US", candidate_source="trend", now=OPEN + timedelta(minutes=20))
    assert result["items"][0]["current_status"] == "UNAVAILABLE"
    assert result["summary"]["ever_confirmed"] == 1
    assert store.value == original


def test_existing_v1_pool_is_not_evaluated_under_new_rules(monkeypatch):
    store = Store()
    store.value = {"items": [{"code": "ABC.US"}]}
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.resolve_session", lambda *a: SESSION)
    result = ConfirmationService(store=store, market_data=object()).run("US", OPEN + timedelta(minutes=20))
    assert result["status"] == "skipped" and "旧规则" in result["reason"]


def test_benchmark_etf_does_not_need_to_outperform_itself_or_gain_rs_points():
    m = {**inputs(), "market_benchmark_self": True, "relative_to_market": 0}
    result = decision(m, {"impact": "unavailable"})
    assert result["proposed_state"] == "CONFIRMED"
    assert result["conditions"]["relative_strength"] is None
    assert result["score_breakdown"]["relative_strength_score"] is None
    assert result["available_score_weight"] == 65


def test_current_quote_below_breakout_does_not_reuse_earlier_bullish_closes():
    now = OPEN + timedelta(minutes=15)
    bars = [
        bar(OPEN + timedelta(minutes=i), close=100.5 if i < 5 else 102, high=101 if i < 5 else 103) for i in range(15)
    ]
    m = metrics(quote(now, price=100.9), bars, quote(now, price=100), history(), SESSION, now)
    assert m["break_above_opening_range"] is False
    assert decision(m, {})["proposed_state"] == "WAIT"


@pytest.mark.parametrize(
    "proposed,status,reason",
    [("CONFIRMED", "PENDING_CONFIRMATION", "确认走强"), ("FAILED", "PENDING_FAILURE", "判定失效")],
)
def test_pending_direction_still_requires_two_distinct_stable_evaluations(proposed, status, reason):
    now = OPEN + timedelta(minutes=15)
    raw = {**decision(inputs(), {}), "proposed_state": proposed}
    first = stabilize(deepcopy(raw), {}, now, now)
    assert first["state"] == "WAIT" and first["current_status"] == status
    assert reason in first["reasons"][-1]["text"]
    repeated = stabilize(deepcopy(raw), first, now, now + timedelta(seconds=30))
    assert repeated["state"] == "WAIT" and repeated["pending_count"] == 1
    later = now + timedelta(minutes=5)
    second = stabilize(deepcopy(raw), repeated, later, later)
    assert second["state"] == proposed
    assert second["current_status"] == ("ACTIVE" if proposed == "CONFIRMED" else "FAILED")


@pytest.mark.parametrize("legacy", [True, False])
def test_pending_failure_ranks_after_wait_and_counts_as_attention_without_rewriting_history(legacy):
    store = Store()

    def item(code, score, status, proposed):
        return dict(
            code=code, state="WAIT", candidate_source="trend", metrics={}, chase_risk="LOW",
            confirmation_score=score, current_status=status, proposed_state=proposed,
        )

    store.value = dict(
        rule_version=config.RULE_VERSION,
        items=[
            item("SBUX.US", 15, "PENDING" if legacy else "PENDING_FAILURE", "FAILED"),
            item("TMO.US", 3.81, "PENDING" if legacy else "PENDING_FAILURE", "FAILED"),
            item("EW.US", 15, "WAIT", "WAIT"),
            item("UP.US", 95, "PENDING" if legacy else "PENDING_CONFIRMATION", "CONFIRMED"),
            item("OLD.US", 100, "PENDING", None),
        ],
    )
    original = deepcopy(store.value)
    # Reading a historical day avoids today's freshness projection; no providers or writes are permitted.
    result = ConfirmationService(store=store, market_data=object()).read(
        "US", trade_date=OPEN.date(), now=OPEN + timedelta(days=1)
    )
    assert [row["code"] for row in result["items"]] == ["UP.US", "EW.US", "SBUX.US", "TMO.US", "OLD.US"]
    assert result["items"][0]["current_status"] == "PENDING_CONFIRMATION"
    assert result["items"][2]["current_status"] == "PENDING_FAILURE"
    assert result["items"][-1]["current_status"] == "PENDING"
    assert result["summary"]["attention"] == 2
    assert result["summary"]["ever_confirmed"] == 0
    assert store.value == original


def test_evaluation_history_projects_saved_pending_direction_without_mutation():
    from types import SimpleNamespace

    rows = [
        {"current_status": "PENDING", "proposed_state": "FAILED", "confirmation_score": 3.81},
        {"current_status": "PENDING", "proposed_state": "CONFIRMED", "confirmation_score": 95},
        {"current_status": "PENDING"},
    ]
    original = deepcopy(rows)
    calls = []

    def evaluations(*args):
        calls.append(args)
        return rows

    service = ConfirmationService(store=SimpleNamespace(evaluations=evaluations))
    result = service.evaluations("US", OPEN.date(), "TMO.US")
    assert [row["current_status"] for row in result] == ["PENDING_FAILURE", "PENDING_CONFIRMATION", "PENDING"]
    assert calls == [("US", OPEN.date(), "TMO.US")]
    assert rows == original


def test_evaluation_api_uses_the_same_pending_projection_as_the_list():
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import intraday_confirmation as api

    calls = []

    def evaluations(*args):
        calls.append(args)
        return [{"current_status": "PENDING", "proposed_state": "FAILED", "confirmation_score": 3.81}]

    service = ConfirmationService(store=SimpleNamespace(evaluations=evaluations))
    app = FastAPI()
    app.include_router(api.router, prefix="/intraday-confirmation")
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        result = client.get("/intraday-confirmation/tmo.us/evaluations?market=US&trade_date=2026-09-21")
    assert result.status_code == 200
    assert result.json()["items"][0]["current_status"] == "PENDING_FAILURE"
    assert calls == [("US", OPEN.date(), "TMO.US")]
