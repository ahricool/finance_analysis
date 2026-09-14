from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories import trend_following as repositories
from finance_analysis.interfaces.api.v1.endpoints import trend_following as endpoints
from finance_analysis.trend_following import state_history
from tests.test_trend_following_repository import _Database, _snapshot

TODAY = date(2026, 9, 14)


@pytest.fixture
def source(monkeypatch):
    database = _Database()
    database.engine.dispose()
    database.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (Instrument, TrendFollowingSnapshot, TrendFollowingSummary):
        model.__table__.create(database.engine)
    sessions = [date(2026, 7, 20) + timedelta(days=i) for i in range(54)]
    sessions = [day for day in sessions if day.weekday() < 5 and day != date(2026, 8, 3)][-35:]
    with database.session_scope() as session:
        session.add_all([Instrument(id=i + 1, market="US", code=f"S{i:02}.US", name=f"Stock {i}") for i in range(60)])
        session.add(Instrument(id=100, market="CN", code="600000.SH", name="CN"))
        snapshot_id = 1
        for day in sessions:
            for i in range(60):
                if i == 59 and day == sessions[-2]:
                    continue
                row = _snapshot(snapshot_id=snapshot_id, code=f"S{i:02}.US", instrument_id=i + 1,
                                trade_date=day, state="WEAKENING" if i == 59 else "ENTRY")
                row.rank = 60 - i if day == sessions[-1] else i + 1
                row.fragility_score = 18.5
                row.trend_duration_days = 14
                session.add(row)
                snapshot_id += 1
        cn = _snapshot(snapshot_id=5000, code="600000.SH", instrument_id=100, trade_date=TODAY)
        cn.market = "CN"
        session.add(cn)
    original = repositories.TrendFollowingRepository
    monkeypatch.setattr(repositories, "TrendFollowingRepository", lambda market: original(market, database))
    monkeypatch.setattr(state_history, "get_market_now",
                        lambda market: datetime.combine(TODAY, datetime.min.time(), timezone.utc))
    preview = Mock(return_value=None)
    monkeypatch.setattr(state_history, "load_preview", preview)
    statements = []
    event.listen(database.engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    return database, sessions, preview, statements


def test_official_top_50_fixed_to_anchor_and_thirty_real_sessions_with_two_queries(source):
    _, sessions, preview, statements = source
    result = state_history.get_state_history("US")
    assert result["anchor_date"] == sessions[-1]
    assert result["dates"] == sessions[-30:]
    assert (sessions[-1] - result["dates"][0]).days > 30
    assert len(result["items"]) == 50
    assert [item["code"] for item in result["items"]] == [f"S{i:02}.US" for i in range(59, 9, -1)]
    assert [item["current_rank"] for item in result["items"]] == list(range(1, 51))
    stock = result["items"][0]
    assert stock["history"][-2] is None
    assert stock["history"][0]["rank"] == 60  # It was outside Top 50 then; still query its full trajectory.
    assert stock["history"][0]["state"] == "WEAKENING"  # Never inferred from rank or scores.
    assert stock["history"][0]["fragility_score"] == 18.5
    assert stock["history"][0]["trend_duration_days"] == 14
    assert len(statements) == 2
    assert all("features" not in statement for statement in statements)
    preview.assert_not_called()


def test_historical_date_chooses_that_dates_top_and_never_reads_future_or_preview(source):
    _, sessions, preview, statements = source
    result = state_history.get_state_history("US", as_of=sessions[-2], limit=3, include_preview=True)
    assert [item["code"] for item in result["items"]] == ["S00.US", "S01.US", "S02.US"]
    assert result["dates"][-1] == sessions[-2]
    assert all(cell["rank"] == 1 for cell in result["items"][0]["history"])
    assert len(statements) == 2
    preview.assert_not_called()


def make_preview(sessions):
    return {
        "market": "US", "trade_date": TODAY.isoformat(), "status": "completed", "preview_time": None,
        "snapshots": [
            {"code": f"S{i:02}.US", "name": f"Stock {i}", "rank": i + 1, "state": "HOLDING", "action": "HOLD"}
            for i in reversed(range(60))
        ],
    }


def test_preview_top_50_with_extra_31st_column_and_bounded_batch(source):
    _, sessions, preview, statements = source
    preview.return_value = make_preview(sessions)
    result = state_history.get_state_history("US", include_preview=True)
    assert len(statements) == 2
    assert result["dates"] == [*sessions[-30:], TODAY]
    assert result["official_count"] == 30 and result["preview_date"] == TODAY
    assert result["anchor_date"] == TODAY
    assert [item["code"] for item in result["items"]] == [f"S{i:02}.US" for i in range(50)]
    assert result["items"][0]["history"][-1]["state"] == "HOLDING"
    assert result["items"][0]["history"][-2]["state"] == "ENTRY"


def test_same_day_official_wins_for_entire_column_and_top_list(source):
    database, sessions, preview, _ = source
    preview.return_value = make_preview(sessions)
    with database.session_scope() as session:
        row = _snapshot(snapshot_id=5001, code="S59.US", instrument_id=60, trade_date=TODAY, state="EXIT")
        session.add(row)
    result = state_history.get_state_history("US", include_preview=True)
    assert result["preview_date"] is None and len(result["dates"]) == 30
    assert [item["code"] for item in result["items"]] == ["S59.US"]
    assert result["items"][0]["history"][-1]["state"] == "EXIT"
    preview.assert_not_called()


@pytest.mark.parametrize("patch", [
    {"status": "failed"}, {"status": "incomplete"}, {"trade_date": "2026-09-11"},
    {"trade_date": "2026-09-15"}, {"market": "CN"}, {"snapshots": []},
])
def test_invalid_preview_falls_back_to_official_with_notice(source, patch):
    _, sessions, preview, _ = source
    preview.return_value = {**make_preview(sessions), **patch}
    result = state_history.get_state_history("US", include_preview=True)
    assert result["anchor_date"] == sessions[-1] and result["preview_date"] is None
    assert result["warnings"]


def test_market_isolation_and_explicit_missing_anchor(source):
    _, sessions, _, _ = source
    cn = state_history.get_state_history("CN")
    assert cn["dates"] == [TODAY] and cn["items"][0]["code"] == "600000.SH"
    missing = state_history.get_state_history("US", as_of=date(2026, 9, 13))
    assert missing["items"] == [] and missing["warnings"]
    assert missing["anchor_date"] == date(2026, 9, 13)  # Do not silently substitute Friday's ranking.
    empty = state_history.get_state_history("US", as_of=sessions[0] - timedelta(days=1))
    assert empty["dates"] == [] and empty["items"] == []


def test_rankless_history_is_missing_and_unranked_anchor_excluded(source):
    database, sessions, _, _ = source
    from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
    from sqlalchemy import update
    with database.session_scope() as session:
        session.execute(update(TrendFollowingSnapshot).where(
            TrendFollowingSnapshot.code == "S59.US", TrendFollowingSnapshot.trade_date == sessions[0],
        ).values(rank=0))
    result = state_history.get_state_history("US", days=35, limit=1)
    assert result["items"][0]["history"][0] is None
    assert state_history.get_state_history("US", as_of=sessions[0], limit=100)["items"][-1]["code"] == "S58.US"


def test_api_validates_limits_dates_and_future_market_day(source, monkeypatch):
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1/trend-following")
    app.dependency_overrides[endpoints.require_current_user] = lambda: object()
    with TestClient(app) as client:
        url = "/api/v1/trend-following/state-history"
        for params in ({"limit": 0}, {"limit": 101}, {"days": 0}, {"days": 121}, {"market": "HK"},
                       {"as_of": "bad"}, {"as_of": "2026-09-15"}):
            assert client.get(url, params=params).status_code == 422
        response = client.get(url, params={"market": "US", "limit": 50})
        assert response.status_code == 200 and len(response.json()["items"]) == 50
        from finance_analysis.market_review.trading_calendar import get_market_now
        now = datetime(2026, 9, 14, 2, tzinfo=timezone.utc)
        monkeypatch.setattr(state_history, "get_market_now", lambda market: get_market_now(market, now))
        assert client.get(url, params={"market": "US", "as_of": "2026-09-14"}).status_code == 422
