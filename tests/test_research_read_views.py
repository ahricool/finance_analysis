"""Regression coverage for bounded research APIs and preview generation isolation."""

import json
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from finance_analysis.core.preview_views import encode
from finance_analysis.trend_following import preview_cache as trend_cache
from finance_analysis.etf_rotation import preview_cache as etf_cache
from finance_analysis.trend_following.table import snapshot_item, table_rows
from finance_analysis.interfaces.api.v1.endpoints import trend_following, etf_rotation, industry_strength
from tests.preview_database import preview_repository


def payload(period=20):
    return {
        "market": "CN", "trend_period": period, "trade_date": "2026-10-14", "status": "completed",
        "preview_time": "2026-10-14T06:00:00.000Z", "rankable_count": 1,
        "snapshots": [{
            "code": "600519.SH", "name": "贵州茅台", "trade_date": "2026-10-14", "rank": 1,
            "alpha_score": 82.123456789, "state": "TRENDING",
            "features": {"box_state": "BOX_READY", "trend_resume": False, "return_20d": 0,
                         "rsi14": None, "risk_sizing": {"stop_price": 12.34}, "unused": [1] * 1000},
            "score_breakdown": {"alpha": {"contributions": {"trend": 32.123456789}}},
        }],
    }


def test_columnar_lists_preserve_precision_null_zero_and_false_without_full_diagnostics():
    source = payload()["snapshots"][0]
    original = deepcopy(source)
    table = table_rows([snapshot_item(source)])
    values = table["rows"][0]
    top = dict(zip(table["columns"], values))
    features = dict(zip(table["feature_columns"], values[len(table["columns"]):]))
    assert top["alpha_score"] == 82.123456789
    assert features["alpha_trend_contribution"] == 32.123456789
    assert features["return_20d"] == 0
    assert features["trend_resume"] is False
    assert "rsi14" not in table["feature_columns"]
    assert "risk_sizing" not in table["feature_columns"]
    assert "unused" not in table["feature_columns"]
    assert source == original
    assert len(encode(table)) < len(encode(source))


def test_views_read_only_requested_rows_and_preserve_diagnostics():
    client = preview_repository()
    trend_cache.save_preview("CN", payload(), repository=client)
    status = json.loads(trend_cache.load_preview_view("CN", "status", repository=client))
    detail = json.loads(trend_cache.load_preview_view("CN", "stock:600519.SH", repository=client))
    assert status["snapshot_count"] == 1
    assert "snapshots" not in status
    assert detail["latest"]["features"]["risk_sizing"]["stop_price"] == 12.34
    assert "snapshots" not in detail["market_context"]


def test_publication_replaces_removed_symbols_failed_results_and_periods():
    client = preview_repository()
    for period in (20, 40, 60):
        trend_cache.save_preview("CN", payload(period), repository=client)
    failed = {**payload(40), "status": "failed", "snapshots": [], "warnings": ["not ready"]}
    trend_cache.save_preview("CN", failed, repository=client)
    assert trend_cache.load_preview_view("CN", "stock:600519.SH", trend_period=40, repository=client) is None
    assert trend_cache.load_preview_view("CN", "stock:600519.SH", trend_period=20, repository=client)
    assert trend_cache.load_preview_view("US", "status", repository=client) is None
    assert json.loads(trend_cache.load_preview_view("CN", "status", trend_period=40, repository=client))["status"] == "failed"


def test_missing_database_preview_returns_none():
    assert trend_cache.load_preview_view("CN", "ranking", repository=preview_repository()) is None


@pytest.mark.parametrize("endpoint,cache,rows_key", [
    (trend_following, trend_cache, "snapshots"), (etf_rotation, etf_cache, "items"),
])
def test_single_security_api_is_exact_date_scoped_and_preserves_missing_semantics(monkeypatch, endpoint, cache, rows_key):
    client = preview_repository()
    data = payload()
    if rows_key == "items":
        data["items"] = data.pop("snapshots")
    cache.save_preview("CN", data, repository=client)
    monkeypatch.setattr(endpoint, "load_preview_view", lambda market, field, **kwargs: cache.load_preview_view(
        market, field, repository=client, **kwargs))
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.require_current_user] = lambda: None
    with TestClient(app) as http:
        assert http.get("/preview/stocks/600519.SH?market=CN&trade_date=2026-10-14").json()["latest"]["code"] == "600519.SH"
        assert http.get("/preview/stocks/600519.SH?market=CN&trade_date=2026-10-13").status_code == 404
        assert http.get("/preview/stocks/MISSING.US?market=CN").status_code == 404
        assert http.get("/preview/stocks/600519.SH?market=US").status_code == 404


def test_official_table_cache_is_separate_invalidated_and_keeps_all_rows(monkeypatch, cache_client):
    from tests.test_trend_following_api_tasks import FakeRepository
    from finance_analysis.trend_following.ranking_cache import RankingCache, invalidate_market

    monkeypatch.setattr(trend_following, "TrendFollowingRepository", FakeRepository)
    result = json.loads(trend_following.ranking_table(date(2026, 8, 28), None, "US", 40).body)
    assert result["table"]["rows"][0][result["table"]["columns"].index("code")] == "AAPL.US"
    assert "items" not in result
    assert RankingCache("US", date(2026, 8, 28), 40, table=True).load()
    assert RankingCache("US", date(2026, 8, 28), 20, table=True).load() is None
    invalidate_market("US")
    assert RankingCache("US", date(2026, 8, 28), 40, table=True).load() is None


@pytest.fixture
def cache_client(monkeypatch):
    from finance_analysis.core import snapshot_cache
    from tests.test_trend_following_ranking_cache import MemoryRedis as RankingRedis

    client = RankingRedis()
    monkeypatch.setattr(snapshot_cache, "redis_client", lambda: client)
    return client


def test_industry_list_excludes_members_and_detail_rejects_another_generation(monkeypatch):
    from finance_analysis.industry_strength.preview import PreviewCache
    from finance_analysis.market_review import trading_calendar

    client = preview_repository()
    cache = PreviewCache(client)
    members = {"industry_code": "881101.TI", "items": [{"code": "600519.SH"}]}
    cache.write({"status": "completed", "result": {
        "trade_date": "2026-10-14", "generated_at": "2026-10-14T06:00:00.000Z", "items": [],
        "constituents": {"881101.TI": members},
    }})
    monkeypatch.setattr("finance_analysis.industry_strength.preview.PreviewCache", lambda: cache)
    monkeypatch.setattr(trading_calendar, "get_market_now", lambda _: datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert industry_strength.preview_ranking()["result"]["constituents"] == {}
    assert industry_strength.preview_constituents("881101.TI", datetime(2026, 10, 14, 6, tzinfo=timezone.utc)) == members
    with pytest.raises(HTTPException) as error:
        industry_strength.preview_constituents("881101.TI", datetime(2026, 10, 14, 5, tzinfo=timezone.utc))
    assert error.value.status_code == 404


def test_legacy_scalar_score_features_survive_a_missing_nested_breakdown():
    row = {"features": {"alpha_trend_contribution": 0, "r2_quality": 81}, "score_breakdown": {}}
    assert snapshot_item(row)["features"]["alpha_trend_contribution"] == 0
    assert snapshot_item(row)["features"]["r2_quality"] == 81
