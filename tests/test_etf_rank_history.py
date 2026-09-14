from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_analysis.etf_rotation import rank_history as history
from finance_analysis.etf_rotation.universe import ETFUniverseMember
from finance_analysis.interfaces.api.v1.endpoints import etf_rotation


@pytest.fixture
def source(monkeypatch):
    rows = [
        {"trade_date": date(2026, 9, 10), "code": "QQQ.US", "rank": 7, "generated_at": None},
        {"trade_date": date(2026, 9, 11), "code": "QQQ.US", "rank": None, "generated_at": None},
    ]
    repository = Mock()
    repository.rank_history.return_value = rows
    monkeypatch.setattr(history, "ETFRotationRepository", lambda market: repository)
    monkeypatch.setattr(history, "get_market_now", lambda market: datetime(2026, 9, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(history, "get_etf_universe", lambda market: [
        ETFUniverseMember("QQQ.US", "Nasdaq", "", "", "", market="US"),
        ETFUniverseMember("NEW.US", "New", "", "", "", market="US"),
        ETFUniverseMember("OFF.US", "Disabled", "", "", "", enabled=False, market="US"),
    ])
    preview = Mock(return_value={
        "status": "completed", "market": "US", "trade_date": "2026-09-14", "preview_time": None,
        "items": [{"code": "QQQ.US", "rank": 2}, {"code": "FORMER.US", "rank": 1}],
    })
    monkeypatch.setattr(history, "load_preview", preview)
    return SimpleNamespace(rows=rows, repository=repository, preview=preview)


def test_current_universe_nulls_and_preview_are_not_recomputed(source):
    result = history.get_rank_history("US")
    assert result["dates"] == ["2026-09-10", "2026-09-11", "2026-09-14"]
    assert result["official_count"] == 2
    assert result["preview_date"] == "2026-09-14"
    assert result["series"] == [
        {"code": "QQQ.US", "name": "Nasdaq", "ranks": [7, None, 2]},
        {"code": "NEW.US", "name": "New", "ranks": [None, None, None]},
    ]
    source.repository.rank_history.assert_called_once_with(
        ["QQQ.US", "NEW.US"], days=30, as_of=date(2026, 9, 14),
    )


def test_official_today_wins_for_the_whole_session(source):
    source.rows.append({"trade_date": date(2026, 9, 14), "code": "QQQ.US", "rank": None, "generated_at": None})
    result = history.get_rank_history("US")
    assert result["preview_date"] is None
    assert result["series"][0]["ranks"][-1] is None
    source.preview.assert_not_called()


@pytest.mark.parametrize("patch", [
    {"trade_date": "2026-09-11"}, {"trade_date": "2026-09-15"},
    {"status": "failed"}, {"status": "incomplete"}, {"market": "CN"}, {"items": []},
])
def test_rejects_stale_future_failed_and_wrong_market_preview(source, patch):
    source.preview.return_value.update(patch)
    assert history.get_rank_history("US")["preview_date"] is None


@pytest.mark.parametrize("kwargs", [{"as_of": date(2026, 9, 11)}, {"include_preview": False}])
def test_historical_or_official_mode_does_not_read_preview(source, kwargs):
    assert history.get_rank_history("US", **kwargs)["preview_date"] is None
    source.preview.assert_not_called()


def test_market_local_today_is_used(monkeypatch, source):
    from finance_analysis.market_review.trading_calendar import get_market_now
    instant = datetime(2026, 9, 14, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(history, "get_market_now", lambda market: get_market_now(market, instant))
    assert history.get_rank_history("US")["preview_date"] is None
    assert source.repository.rank_history.call_args.kwargs["as_of"] == date(2026, 9, 13)


def test_empty_history(source):
    source.rows.clear()
    source.preview.return_value = None
    result = history.get_rank_history("US")
    assert result["dates"] == [] and result["official_count"] == 0
    assert all(series["ranks"] == [] for series in result["series"])


def test_api_contract_and_validation(source):
    app = FastAPI()
    app.include_router(etf_rotation.router, prefix="/api/v1/etf-rotation")
    app.dependency_overrides[etf_rotation.require_current_user] = lambda: object()
    with TestClient(app) as client:
        response = client.get("/api/v1/etf-rotation/rank-history?market=US&days=30")
        assert response.status_code == 200
        assert response.json()["series"][0]["ranks"] == [7, None, 2]
        for query in ("days=0", "days=121", "market=HK", "as_of=bad"):
            assert client.get(f"/api/v1/etf-rotation/rank-history?{query}").status_code == 422


def test_preview_is_extra_to_thirty_official_sessions(source):
    from datetime import timedelta
    sessions = [date(2026, 7, 15) + timedelta(days=index) for index in range(59)]
    sessions = [day for day in sessions if day.weekday() < 5][-30:]
    source.rows[:] = [
        {"trade_date": day, "code": "QQQ.US", "rank": 5, "generated_at": None}
        for day in sessions
    ]
    result = history.get_rank_history("US")
    assert result["official_count"] == 30 and len(result["dates"]) == 31
    assert result["dates"][:30] == [day.isoformat() for day in sessions]
