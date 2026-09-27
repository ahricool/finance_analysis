"""Homepage payload stays bounded while retaining complete transition counts."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.v1.endpoints import trend_following as api
from finance_analysis.trend_following.dashboard import dashboard_summary

DAY = date(2026, 9, 25)
PREVIOUS = date(2026, 9, 24)


class Repository:
    def __init__(self, market):
        self.market = market

    def latest_trade_date(self):
        return DAY

    def previous_trade_date(self, day):
        assert day == DAY
        return PREVIOUS

    def summary_by_date(self, day):
        if day != DAY:
            return None
        return {"market_regime": "RISK_ON", "market_score": 72.4,
                "score_breakdown": {"trend": 0, "breadth": 71},
                "features": {"lifecycle_counts": {"IGNITION": 12}, "high_fragility_count": 23,
                             "unused": "x" * 10000}}

    def dashboard_state_rows(self, day):
        states = ["CANDIDATE", "TRENDING", "WEAKENING", "BROKEN", "WATCHING", "IDLE"]
        return [{"code": f"{index:06d}.{self.market}", "name": str(index), "rank": index + 1,
                 "state": states[index % 6] if day == DAY else "IDLE"}
                for index in range(6000)]


@pytest.mark.parametrize("market", ["CN", "US"])
def test_dashboard_http_is_bounded_and_matches_ranking_changes(monkeypatch, market):
    monkeypatch.setattr(api, "TrendFollowingRepository", Repository)
    app = FastAPI()
    app.include_router(api.router, prefix="/trend-following")
    app.dependency_overrides[api.require_current_user] = lambda: object()
    client = TestClient(app)
    response = client.get("/trend-following/dashboard", params={"market": market})
    assert response.status_code == 200
    result = response.json()
    assert result["market"] == market
    assert result["trade_date"] == DAY.isoformat()
    assert result["score_breakdown"] == {"trend": 0, "breadth": 71, "risk": None}
    assert result["features"] == {"lifecycle_counts": {"IGNITION": 12}, "high_fragility_count": 23}
    assert result["changes"]["state_counts"] == dict.fromkeys(["CANDIDATE", "TRENDING", "WEAKENING", "BROKEN"], 1000)
    assert len(response.content) < 2000
    assert "items" not in result and "candidates" not in result
    repo = Repository(market)
    repo.change_rows = repo.dashboard_state_rows
    old_changes = api._changes(repo, DAY, repo.dashboard_state_rows(DAY), repo.summary_by_date(DAY))
    highlights = result["changes"]["highlights"]
    expected = [row for row in old_changes["transitions"] if row["current_state"] in result["changes"]["state_counts"]]
    assert highlights == [{key: row[key] for key in highlights[0]} for row in expected[:3]]
    assert client.get("/trend-following/dashboard?market=HK").status_code == 422
    assert client.get("/trend-following/dashboard?trade_date=2026-09-01").status_code == 404
    app.dependency_overrides.clear()
    assert client.get("/trend-following/dashboard").status_code == 401


def test_no_previous_snapshot_and_new_or_unchanged_stocks():
    repo = Repository("CN")
    repo.previous_trade_date = lambda day: None
    result = dashboard_summary(repo, DAY)
    assert result["changes"] == {"previous_trade_date": None,
                                 "state_counts": dict.fromkeys(["CANDIDATE", "TRENDING", "WEAKENING", "BROKEN"], 0),
                                 "highlights": []}
    repo.previous_trade_date = lambda day: PREVIOUS
    repo.dashboard_state_rows = lambda day: ([{"code": "new", "state": "TRENDING"},
                                             {"code": "same", "state": "TRENDING"}] if day == DAY else
                                            [{"code": "same", "state": "TRENDING"}])
    assert dashboard_summary(repo, DAY)["changes"]["highlights"] == []
    repo.dashboard_state_rows = lambda day: []
    assert dashboard_summary(repo, DAY) is None
