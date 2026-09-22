from contextlib import nullcontext
from datetime import datetime, date, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.intraday_confirmation.engine import metrics, decision, stabilize
from finance_analysis.intraday_confirmation.session import Session, resolve_session
from finance_analysis.intraday_confirmation.service import ConfirmationService
from finance_analysis.intraday_confirmation.trend import temporary_trend
from finance_analysis.integrations.market_data.models import MarketBar, MarketQuote, Market, Adjustment
from finance_analysis.trend_following.preview_cache import json_ready

TZ = ZoneInfo("America/New_York")
OPEN = datetime(2026, 9, 21, 9, 30, tzinfo=TZ)
SESSION = Session("US", OPEN, OPEN.replace(hour=16, minute=0), date(2026, 9, 18))


def bar(start, close=102, high=None, low=100, volume=500):
    return MarketBar(
        symbol="ABC.US",
        market=Market.US,
        interval="5m",
        trade_date=start.date(),
        bar_time=start,
        bar_start=start,
        bar_end=start + timedelta(minutes=5),
        open=100,
        high=high or max(101, close),
        low=low,
        close=close,
        volume=volume,
        amount=None,
        currency="USD",
        adjustment=Adjustment.RAW,
        provider="yfinance",
    )


def quote(stamp=None, price=102, pre_close=100, opened=100):
    return MarketQuote(
        symbol="ABC.US",
        market=Market.US,
        provider="yfinance",
        currency="USD",
        price=price,
        open_price=opened,
        high=max(price, opened, 103),
        low=min(price, opened, 99),
        pre_close=pre_close,
        volume=50000,
        quote_time=stamp or OPEN + timedelta(minutes=15),
    )


def history():
    return [SimpleNamespace(trade_date=date(2026, 8, 20) + timedelta(days=i), volume=10000) for i in range(20)]


def inputs():
    now = OPEN + timedelta(minutes=15)
    bars = [bar(OPEN, close=100.5, high=101), bar(OPEN + timedelta(minutes=5)), bar(OPEN + timedelta(minutes=10))]
    return metrics(quote(now), bars, quote(now, price=100), history(), SESSION, now)


def test_completed_windows_only_and_vwap_gaps():
    now = OPEN + timedelta(minutes=8)
    m = metrics(quote(now), [bar(OPEN), bar(OPEN + timedelta(minutes=5))], None, history(), SESSION, now)
    assert m["return_5m"] == pytest.approx(0.02)
    assert m["return_15m"] is None and m["return_30m"] is None
    assert m["high_15m"] is None
    late = OPEN + timedelta(minutes=15)
    m = metrics(
        quote(late),
        [bar(OPEN + timedelta(minutes=5)), bar(OPEN + timedelta(minutes=10))],
        None,
        history(),
        SESSION,
        late,
    )
    assert m["vwap"] is None and m["volume_ratio"] is None and m["return_15m"] is None


def test_breakout_relative_strength_and_volume_confirm():
    m = inputs()
    assert m["break_above_opening_range"] is True
    assert m["relative_to_market"] == pytest.approx(0.02)
    assert m["volume_ratio"] == pytest.approx(1500 / (10000 * 15 / 390))
    assert "approximation" in m["volume_method"]
    result = decision(m, {"impact": "intact"})
    assert result["proposed_state"] == "CONFIRMED"
    assert {"opening_breakout", "relative_market", "volume"} <= {r["code"] for r in result["reasons"]}


def test_zero_volume_unavailable_is_not_failure():
    m = inputs()
    m.update(volume_ratio=None, volume_status="unavailable", vwap=None, vwap_distance_pct=None)
    result = decision(m, {"impact": "unavailable"})
    assert result["proposed_state"] == "WAIT"
    assert not any(r["code"] == "opening_breakdown" for r in result["reasons"])
    now = OPEN + timedelta(minutes=15)
    z = metrics(
        quote(now), [bar(OPEN + timedelta(minutes=i), volume=0) for i in (0, 5, 10)], None, history(), SESSION, now
    )
    assert z["vwap"] is None


def test_opening_breakdown_gap_fade_needs_structure():
    m = inputs()
    m.update(
        break_above_opening_range=False,
        break_below_opening_range=True,
        gap_pct=0.04,
        intraday_return=-0.03,
        vwap_distance_pct=-0.012,
        relative_to_market=-0.02,
        return_15m=-0.02,
    )
    result = decision(m, {"impact": "deteriorating"})
    assert result["proposed_state"] == "FAILED"
    assert {"opening_breakdown", "gap_fade"} <= {r["code"] for r in result["reasons"]}
    m.update(break_below_opening_range=False, vwap_distance_pct=-0.001, relative_to_market=-0.001)
    assert decision(m, {"impact": "intact"})["proposed_state"] == "WAIT"


def test_failed_latch_distinct_observations_and_confirmed_to_failed():
    now = OPEN + timedelta(minutes=15)
    initial = decision(inputs(), {"impact": "intact"})
    first = stabilize(initial.copy(), None, now, now)
    assert first["state"] == "WAIT"
    repeat = stabilize(initial.copy(), first, now, now + timedelta(seconds=30))
    assert repeat["state"] == "WAIT" and repeat["pending_count"] == 1
    later = now + timedelta(minutes=5)
    confirmed = stabilize(initial.copy(), repeat, later, later)
    assert confirmed["state"] == "CONFIRMED"
    failure = {**initial, "proposed_state": "FAILED"}
    first_fail = stabilize(failure.copy(), confirmed, later + timedelta(minutes=5), later)
    assert first_fail["state"] == "CONFIRMED"
    failed = stabilize(failure.copy(), first_fail, later + timedelta(minutes=10), later)
    assert failed["state"] == "FAILED"
    recovered = stabilize(initial.copy(), failed, later + timedelta(minutes=15), later)
    assert recovered["state"] == "FAILED" and recovered["current_price_recovered"]
    assert recovered["failed_at"] == failed["failed_at"]


def test_stale_quotes_time_exposed_and_cannot_advance():
    m = inputs()
    now = OPEN + timedelta(hours=1)
    old_quote = quote(OPEN + timedelta(minutes=15))
    m = metrics(
        old_quote,
        [bar(OPEN + timedelta(minutes=i)) for i in (0, 5, 10)],
        quote(old_quote.quote_time, price=100),
        history(),
        SESSION,
        now,
    )
    assert m["quote_time"] == old_quote.quote_time and m["data_age_seconds"] == 2700
    assert not m["data_fresh"]
    assert decision(m, {"impact": "intact"})["proposed_state"] == "WAIT"


def test_high_chase_can_still_confirm():
    m = inputs()
    m.update(gap_pct=0.07, return_from_previous_close=0.09, vwap_distance_pct=0.06)
    result = decision(m, {"impact": "intact"})
    assert result["proposed_state"] == "CONFIRMED" and result["chase_risk"] == "HIGH"


class Cache:
    def __init__(self):
        self.value = None

    def load(self, market, day):
        return self.value

    def save(self, session, payload):
        self.value = json_ready(payload)

    def lock(self, session):
        return nullcontext()


def test_freeze_only_before_open_candidate_not_expanded(monkeypatch):
    cache = Cache()
    calls = []
    row = dict(
        code="ABC.US",
        name="ABC",
        candidate_source="trend",
        candidate_trade_date=SESSION.previous_date,
        candidate_reason=["昨日 CANDIDATE"],
        source_generated_at=OPEN - timedelta(days=1),
        official_trend=None,
    )
    repo = SimpleNamespace(candidates=lambda *args: calls.append(args) or [row.copy()])
    service = ConfirmationService(cache, repo, SimpleNamespace())
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.resolve_session", lambda *args: SESSION)
    assert service.run("US", OPEN + timedelta(minutes=5))["status"] == "skipped"
    assert not calls
    assert service.run("US", OPEN - timedelta(minutes=5))["status"] == "frozen"
    assert cache.value["items"][0]["confirmation_score"] is None
    assert cache.value["items"][0]["chase_risk"] == "UNKNOWN"
    assert calls[0][1] == SESSION.previous_date
    assert service.run("US", OPEN - timedelta(minutes=1))["status"] == "already_frozen"
    assert len(calls) == 1
    requested = []

    def quotes(codes, **kwargs):
        requested.append(codes)
        return SimpleNamespace(data={"ABC.US": quote(), "SPY.US": quote(price=100), "ROCKET.US": quote(price=900)})

    service.market_data = SimpleNamespace(
        get_realtime_quotes=quotes,
        get_minute_bars=lambda *args, **kwargs: SimpleNamespace(data={}),
        get_daily_bars=lambda *args, **kwargs: SimpleNamespace(data={}),
    )
    service.run("US", OPEN + timedelta(minutes=15))
    assert requested == [["ABC.US", "SPY.US"]]
    assert [r["code"] for r in cache.value["items"]] == ["ABC.US"]
    assert "minute_bars" not in str(cache.value)
    # GET uses the cache only: no repository/provider calls.
    service.repository = object()
    service.market_data = object()
    result = service.read("US", now=OPEN)
    assert result["summary"]["total"] == 1
    assert "official_trend" not in result["items"][0]


def test_session_holiday_dst_early_close_and_lunch():
    thanksgiving = datetime(2026, 11, 26, 10, tzinfo=TZ)
    assert resolve_session("US", thanksgiving) is None
    early = resolve_session("US", datetime(2026, 11, 27, 10, tzinfo=TZ))
    assert early.closed.hour == 13
    assert early.previous_date == date(2026, 11, 25)
    assert early.opened.utcoffset() == timedelta(hours=-5)
    cn_open = datetime(2026, 9, 21, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    cn = Session("CN", cn_open, cn_open.replace(hour=15, minute=0), date(2026, 9, 18))
    assert cn.elapsed(cn.closed) == 240
    assert not cn.active(cn_open.replace(hour=12))
    assert cn.elapsed(cn_open.replace(hour=13, minute=30)) == 150


def test_temporary_trend_pure_reuses_features_no_writes():
    from finance_analysis.trend_following.models import DailyBar
    from finance_analysis.trend_following.features import calculate_features

    bars = [
        DailyBar(SESSION.previous_date - timedelta(days=29 - i), 70 + i, 71 + i, 69 + i, 70 + i, 10000)
        for i in range(30)
    ]
    official = dict(
        state="TRENDING",
        trend_lifecycle="EXPANSION",
        trend_score=70,
        fragility_score=18,
        trend_duration_days=9,
        features={**calculate_features(bars), "weighted_slope_percentile": 75},
    )
    q = quote(pre_close=99)
    out = temporary_trend(official, bars, q, bars, q, SESSION.day, SESSION.previous_date)
    assert out["temporary_trend_state"] is not None
    assert out["temporary_lifecycle"] is not None
    assert out["fragility_delta"] is None
    assert official["state"] == "TRENDING" and len(bars) == 30


def test_relative_requires_synchronized_quotes_and_true_break_closes():
    now = OPEN + timedelta(minutes=15)
    m = metrics(
        quote(now),
        [
            bar(OPEN, close=100.5, high=101),
            bar(OPEN + timedelta(minutes=5), close=100.5),
            bar(OPEN + timedelta(minutes=10), close=102),
        ],
        quote(OPEN + timedelta(minutes=5), price=100),
        history(),
        SESSION,
        now,
    )
    assert m["relative_to_market"] is None
    assert m["break_above_opening_range"] is False


def test_get_api_read_only_filters_and_post_admin(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import intraday_confirmation as api
    from finance_analysis.tasks.celery.jobs.intraday_confirmation.tasks import run_intraday_confirmation_us

    cache = Cache()
    cache.value = dict(
        market="US",
        trade_date="2026-09-21",
        candidate_trade_date="2026-09-18",
        generated_at=OPEN.isoformat(),
        status="frozen",
        warnings=[],
        items=[
            dict(
                code="ABC.US",
                name="ABC",
                candidate_source="trend",
                candidate_trade_date="2026-09-18",
                candidate_reason=["昨日趋势"],
                source_generated_at=OPEN.isoformat(),
                state="WAIT",
                confirmation_score=None,
                available_score_weight=0,
                chase_risk="UNKNOWN",
                reasons=[],
                metrics={},
                trend={},
            )
        ],
    )
    service = ConfirmationService(cache=cache, repository=object(), market_data=object())
    app = FastAPI()
    app.include_router(api.router, prefix="/intraday-confirmation")
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    sent = []
    monkeypatch.setattr(
        run_intraday_confirmation_us, "apply_async", lambda **kw: sent.append(kw) or SimpleNamespace(id="job")
    )

    def deny():
        raise HTTPException(403, "admin only")

    app.dependency_overrides[api.require_admin] = deny
    with TestClient(app) as client:
        assert client.get("/intraday-confirmation?market=US").json()["summary"]["total"] == 1
        assert client.get("/intraday-confirmation?market=US&state=FAILED").json()["items"] == []
        assert client.get("/intraday-confirmation?market=HK").status_code == 422
        detail = client.get("/intraday-confirmation/ABC.US?market=US")
        assert detail.status_code == 200
        assert detail.json()["confirmation_score"] is None
        assert detail.json()["available_score_weight"] == 0
        assert detail.json()["chase_risk"] == "UNKNOWN"
        assert client.get("/intraday-confirmation/ROCKET.US?market=US").status_code == 404
        assert client.post("/intraday-confirmation/run", json={"market": "US"}).status_code == 403
        app.dependency_overrides[api.require_admin] = lambda: SimpleNamespace(id=1)
        assert client.post("/intraday-confirmation/run", json={"market": "US"}).status_code == 202
        assert sent[0]["queue"] == "alerts"
        assert sent[0]["kwargs"]["_triggered_by_uid"] == 1


def test_tencent_capability_only_requests_selected_codes():
    from finance_analysis.integrations.market_data.providers.easyquotation import EasyQuotationProvider
    from finance_analysis.integrations.market_data.registry import ProviderRegistry, REALTIME_QUOTES
    from finance_analysis.integrations.market_data.service import MarketDataService

    calls = []

    def real(codes, prefix):
        calls.append(codes)
        return {
            "sh600001": {
                "now": 10,
                "open": 10,
                "close": 9.9,
                "high": 10,
                "low": 10,
                "volume": 1000,
                "date": "2026-09-21",
                "time": "10:00:00",
            }
        }

    provider = EasyQuotationProvider(client_factory=lambda: SimpleNamespace(real=real))
    registry = ProviderRegistry()
    registry.register("easyquotation", provider, capabilities={REALTIME_QUOTES})
    service = MarketDataService(registry=registry)
    result = service.get_realtime_quotes(["600001.SH"], providers=("easyquotation",))
    assert list(result.data) == ["600001.SH"]
    assert calls == [["sh600001"]]


def test_outage_resets_pending_and_does_not_unlatch_confirmation():
    now = OPEN + timedelta(minutes=15)
    initial = decision(inputs(), {"impact": "intact"})
    pending = stabilize(initial.copy(), None, now, now)
    outage = stabilize({**initial, "proposed_state": "WAIT"}, pending, None, now)
    assert outage["pending_count"] == 0
    recovered = stabilize(initial.copy(), outage, now + timedelta(minutes=5), now)
    assert recovered["state"] == "WAIT"
    latched = stabilize({**initial, "proposed_state": "WAIT"}, {**pending, "state": "CONFIRMED"}, None, now)
    assert latched["state"] == "CONFIRMED"


def test_network_elapsed_time_is_used_for_quotes(monkeypatch):
    # A quote stamped after task start is normal when quote retrieval takes time.
    times = iter([100, 110])
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.monotonic", lambda: next(times))
    now = OPEN + timedelta(minutes=15)
    q = quote(now + timedelta(seconds=5))
    cache = Cache()
    md = SimpleNamespace(
        get_realtime_quotes=lambda *a, **kw: SimpleNamespace(data={"ABC.US": q, "SPY.US": q}),
        get_minute_bars=lambda *a, **kw: SimpleNamespace(
            data={"ABC.US": [bar(OPEN + timedelta(minutes=i)) for i in (0, 5, 10)]}
        ),
        get_daily_bars=lambda *a, **kw: SimpleNamespace(data={}),
    )
    service = ConfirmationService(cache=cache, market_data=md)
    service._evaluate(SESSION, dict(items=[dict(code="ABC.US", state="WAIT")]), now)
    row = cache.value["items"][0]
    assert row["metrics"]["quote_usable"] and row["metrics"]["data_fresh"]
    assert datetime.fromisoformat(row["generated_at"]) == now + timedelta(seconds=10)


@pytest.mark.parametrize("missing", ["quote", "minutes", "stale"])
def test_unavailable_observation_has_no_score_or_low_risk(missing):
    now = OPEN + timedelta(minutes=15)
    q = None if missing == "quote" else quote()
    bars = [] if missing == "minutes" else [bar(OPEN + timedelta(minutes=i)) for i in (0, 5, 10)]
    if missing == "stale":
        now += timedelta(hours=1)
    m = metrics(q, bars, None, history(), SESSION, now)
    result = decision(m, {"impact": "intact"})
    assert result["chase_risk"] == "UNKNOWN"
    assert result["confirmation_score"] is None
    assert result["available_score_weight"] == 0
    assert all(v is None for v in result["score_breakdown"].values())
    assert "data_unavailable" in [r["code"] for r in result["reasons"]]


def test_partial_score_excludes_missing_dimensions_without_penalizing_them():
    m = inputs()
    m.update(relative_to_market=None, volume_ratio=None)
    result = decision(m, {"impact": "unavailable"})
    assert result["available_score_weight"] == 45
    assert result["confirmation_score"] == 100
    assert result["score_breakdown"]["relative_strength_score"] is None
    assert result["proposed_state"] == "WAIT"
    m.update(break_above_opening_range=None, vwap_distance_pct=None, return_15m=None)
    result = decision(m, {"impact": "unavailable"})
    assert result["confirmation_score"] is None
    assert result["available_score_weight"] == 0
    assert result["chase_risk"] == "UNKNOWN"
    m["relative_to_market"] = -0.02
    result = decision(m, {"impact": "unavailable"})
    assert result["confirmation_score"] == 0  # Observed weakness, not missing evidence.
    assert result["available_score_weight"] == 25


@pytest.mark.parametrize("state", ["CONFIRMED", "FAILED"])
def test_outage_preserves_latched_state_and_recovery_recomputes_score(state):
    now = OPEN + timedelta(minutes=15)
    old = {"state": state, "max_confirmation_score": 95}
    m = metrics(None, [], None, [], SESSION, now)
    outage = stabilize(decision(m, {"impact": "unavailable"}), old, None, now)
    assert outage["state"] == state
    assert outage["chase_risk"] == "UNKNOWN"
    assert outage["confirmation_score"] is None
    assert outage["max_confirmation_score"] == 95
    recovered = stabilize(decision(inputs(), {"impact": "intact"}), outage, now, now)
    assert recovered["state"] == state
    assert recovered["chase_risk"] == "LOW"
    assert recovered["confirmation_score"] == 100
    assert recovered["available_score_weight"] == 100


def test_null_score_sorts_after_observed_zero_within_state():
    cache = Cache()
    cache.value = {
        "items": [
            {"code": "A.US", "state": "CONFIRMED", "confirmation_score": None, "chase_risk": "UNKNOWN"},
            {"code": "B.US", "state": "CONFIRMED", "confirmation_score": 0, "chase_risk": "LOW"},
            {"code": "C.US", "state": "WAIT", "confirmation_score": 100, "chase_risk": "LOW"},
        ]
    }
    result = ConfirmationService(cache=cache, repository=object(), market_data=object()).read("US", now=OPEN)
    assert [r["code"] for r in result["items"]] == ["B.US", "A.US", "C.US"]
