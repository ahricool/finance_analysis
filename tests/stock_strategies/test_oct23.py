"""Frozen October 23 identities, threshold boundaries and forward observation."""

from datetime import date, datetime, timedelta, timezone

import pytest

from finance_analysis.stock_strategies.engine import advance, initial_state
from finance_analysis.stock_strategies.features import DataNotReady
from finance_analysis.stock_strategies.registry import definition
from finance_analysis.stock_strategies.service import StockStrategyService
from finance_analysis.stock_strategies.signals import decide
from .helpers import inputs
from .test_service_api import Loader, lock

CN = definition("trend_quality35", "CN")
US = definition("ma_market_dd30", "US")


def quality_inputs():
    data = inputs(market="CN")
    data.trends[60] = {c: dict(trend_score=55, rs_score=45, path_score=65, trend_candidate=True) for c in data.stocks}
    data.etfs = ("SPY.US",)
    data.etf_regime = None  # Neither new strategy depends on ETF market state.
    return data


@pytest.mark.parametrize(
    "score,buy,exit_", [(60, True, False), (59.99, False, False), (35, False, False), (34.99, False, True)]
)
def test_cn_market_hysteresis_and_stock_only(score, buy, exit_):
    data = quality_inputs()
    data.regimes[20]["score"] = score
    result = decide(CN, initial_state(), data)
    assert bool(result["candidates"]) == buy
    assert bool(result["exits"]["A.US"]) == exit_
    assert all(c["type"] == "STOCK" for c in result["candidates"])


@pytest.mark.parametrize(
    "field,value", [("trend_score", 54.99), ("rs_score", 44.99), ("path_score", 64.99), ("trend_candidate", False)]
)
def test_cn_quality_rejects_each_failed_condition(field, value):
    data = quality_inputs()
    data.trends[60]["A.US"][field] = value
    assert [c["code"] for c in decide(CN, initial_state(), data)["candidates"]] == ["B.US"]


def test_quality_sort_missing_evidence_and_ma_exit():
    data = quality_inputs()
    data.trends[60]["B.US"]["trend_score"] = 60
    assert [c["code"] for c in decide(CN, initial_state(), data)["candidates"]] == ["B.US", "A.US"]
    data.features["B.US"]["ma20"] = 101
    assert decide(CN, initial_state(), data)["exits"]["B.US"] == ["收盘跌破MA20"]
    del data.trends[60]["A.US"]["path_score"]
    with pytest.raises(DataNotReady, match="路径质量"):
        decide(CN, initial_state(), data)


@pytest.mark.parametrize(
    "score,buy,exit_", [(65, True, False), (64.99, False, False), (40, False, False), (39.99, False, True)]
)
def test_us_market_gate_on_combined_pool(score, buy, exit_):
    data = inputs()
    data.etfs = ("SPY.US",)
    data.etf_regime = None
    data.regimes[20]["score"] = score
    result = decide(US, initial_state(), data)
    assert bool(result["candidates"]) == buy
    assert bool(result["exits"]["SPY.US"]) == exit_
    if buy:
        assert {c["type"] for c in result["candidates"]} == {"STOCK", "ETF"}


@pytest.mark.parametrize("spec", [CN, US])
def test_market_score_missing_waits_and_missing_close_still_liquidates(spec):
    data = quality_inputs()
    data.regimes[20]["score"] = 0
    data.features["A.US"]["valid"] = False
    assert decide(spec, initial_state(), data)["exits"]["A.US"]
    data.regimes[20]["score"] = float("nan")
    with pytest.raises(DataNotReady, match="市场分数"):
        decide(spec, initial_state(), data)


def test_us_strict_dd30_and_three_exchange_opens_including_weekend():
    days = [date(2026, 10, d) for d in (19, 20, 21, 22, 23, 26, 27, 28)]
    state = initial_state()
    previous = 100
    for i, day in enumerate(days):
        price = 70 if i == 2 else 69 if i >= 3 else 100
        data = inputs(
            day,
            {"A.US": (previous, price), "B.US": (100, 100), "SPY.US": (100, 100)},
            {"A.US": previous, "B.US": 100, "SPY.US": 100},
        )
        data.next_day = days[i + 1] if i + 1 < len(days) else day + timedelta(days=1)
        if i:
            for code in data.prices:
                data.prices[code][days[i - 1].isoformat()] = previous if code == "A.US" else 100
        # Keep individual MA exits out of the account-risk test.
        for f in data.features.values():
            f.update(ma20=50, ma50=40, ma200=30)
        state, snapshot = advance(US, state, data, days[0])
        if i == 2:
            assert not state["stopped"]  # exactly 30% is not strictly greater
        if i == 3:
            assert state["pause_remaining"] == 3
        if 4 <= i <= 6:
            assert not state["positions"]
            assert not any(f["action"] == "BUY" for f in snapshot["payload"]["fills"])
        if i == 7:
            assert state["positions"] and not state["stopped"]
            assert state["max_drawdown"] <= -0.30
        previous = price


def test_new_strategy_does_not_backfill_before_selection_date(repository):
    repository.launch(date(2026, 10, 19), "US", lambda: Loader().freeze("US"))

    class SessionLoader(Loader):
        def load(self, market, day, universe, anchor_dates=()):
            result = super().load(market, day, universe, anchor_dates)
            result.next_day = date(2026, 10, 26)
            return result

    loader = SessionLoader()
    service = StockStrategyService(repository, loader, (US,), lock)
    assert not service.run("US", now=datetime(2026, 10, 23, 2, tzinfo=timezone.utc))["results"]
    assert not loader.loads
    assert service.run("US", now=datetime(2026, 10, 24, 2, tzinfo=timezone.utc))["success"] == 1
    state = repository.state(US, "US")
    assert state["start_date"] == date(2026, 10, 23)
    assert state["payload"]["positions"] == {}
    assert loader.loads == [date(2026, 10, 23)]


def test_dd_pause_delayed_liquidation_waits_until_following_open():
    day = date(2026, 10, 19)
    state, _ = advance(US, initial_state(), inputs(day), day)
    state, _ = advance(US, state, inputs(day + timedelta(days=1)), day)
    state.update(stopped=True, pause_remaining=0)
    state["plan"]["exits"] = {"A.US": ["账户回撤触发清仓与暂停"]}
    state, snapshot = advance(US, state, inputs(day + timedelta(days=2)), day)
    assert [f["action"] for f in snapshot["payload"]["fills"]] == ["SELL"]
    assert state["stopped"] and not state["positions"]
    state, snapshot = advance(US, state, inputs(day + timedelta(days=3)), day)
    assert [f["action"] for f in snapshot["payload"]["fills"]] == ["BUY"]
    assert not state["stopped"]


def test_market_context_projects_path_and_boolean_without_loading_feature_payload(repository):
    from finance_analysis.database.models.etf_rotation import ETFMarketRotationSnapshot
    from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary
    from sqlalchemy import event, insert

    with repository.db.get_session() as session:
        engine = session.get_bind()
    for model in (ETFMarketRotationSnapshot, TrendFollowingSummary, TrendFollowingSnapshot):
        model.__table__.create(engine)
    day = date(2026, 10, 23)
    with engine.begin() as conn:
        conn.execute(
            insert(TrendFollowingSnapshot).values(
                id=1,
                instrument_id=1,
                market="CN",
                trend_period=60,
                trade_date=day,
                code="600000.SH",
                universe_key="cn_trend",
                market_regime="RISK_ON",
                market_score=80,
                rank=1,
                trend_score=55,
                rs_score=45,
                breakout_score=0,
                alpha_score=0,
                features={"path_score": 65, "trend_candidate": True, "unused_large_payload": "x" * 10000},
                score_breakdown={},
                setup="NONE",
                state="WATCHING",
                reference_price=100,
                atr=5,
            )
        )
    statements = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, parameters, context, many: statements.append(statement),
    )
    _, _, _, trends = repository.market_context("CN", day)
    assert trends == {"600000.SH": dict(trend_score=55, rs_score=45, path_score=65, trend_candidate=True)}
    assert len(statements) == 3  # Fixed market-level batch queries, not per-security reads.
    assert not repository.market_context("CN", day + timedelta(days=1))[3]


def test_new_strategy_api_descriptions_are_available_without_starting_accounts(repository):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from finance_analysis.interfaces.api.deps import require_current_user
    from finance_analysis.interfaces.api.v1.endpoints import stock_strategies as api

    service = StockStrategyService(repository, Loader(), lock_factory=lock)
    app = FastAPI()
    app.include_router(api.router, prefix="/strategies")
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        for spec, market in ((CN, "CN"), (US, "US")):
            response = client.get(f"/strategies/{spec.key}?market={market}")
            assert response.status_code == 200
            body = response.json()
            assert body["strategy"]["source_id"] == spec.source_id(market)
            assert body["days"] == [] and body["start_date"] is None
            assert any("2026-10-23" in r["text"] for r in body["strategy"]["rules"])
            assert repository.state(spec, market) is None
