from datetime import date, datetime, timedelta
from types import SimpleNamespace as Obj
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.industry_strength import preview as module
from finance_analysis.industry_strength.preview import IndustryPreviewService, PreviewCache
from finance_analysis.industry_strength.features import overlay
from finance_analysis.interfaces.api.v1.schemas.industry_strength import PreviewResponse

DAY = date(2026, 9, 16)
DAYS = [DAY - timedelta(days=i) for i in range(20, -1, -1)]

STAMP = datetime.combine(DAY, datetime.min.time(), ZoneInfo("Asia/Shanghai")).replace(hour=11)


class Redis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex):
        self.values[key] = value


def quote(price=150, stamp=STAMP, pre_close=120):
    return Obj(price=price, quote_time=stamp, pre_close=pre_close, amount=20, volume=2)


class Data:
    def __init__(self):
        self.stock_calls = []
        self.stock_history_end = DAYS[-2]
        self.history_calls = 0
        self.catalog_calls = 0
        self.member_calls = 0
        self.incomplete_history = False
        self.benchmark_price = 120
        self.stale_benchmark = False

    def get_index_history(self, *args):
        self.history_calls += 1
        days = DAYS[:-2] if self.incomplete_history else DAYS
        return [Obj(trade_date=d, close=100 + i, amount=100, volume=10) for i, d in enumerate(days)], STAMP

    def get_industry_catalog(self):
        self.catalog_calls += 1
        return [{"thscode": f"{i:06d}.TI", "name": str(i)} for i in range(20)]

    def get_index_constituents(self, code):
        self.member_calls += 1
        return [{"thscode": "600001.SH", "name": "共同成分"}]

    def get_daily_bars(self, codes, start, end, **kwargs):
        assert start == DAYS[0] and end == self.stock_history_end
        assert kwargs == {"adjustment": "forward", "source_policy": "db_only"}
        self.stock_calls.append((codes, kwargs))
        return Obj(data={c: [Obj(trade_date=d, close=100, amount=100, volume=10) for d in DAYS] for c in codes})

    def get_index_quotes(self, codes):
        return {
            c: quote(
                self.benchmark_price if c == "000300.SH" else 150,
                STAMP - timedelta(days=1) if c == "000300.SH" and self.stale_benchmark else STAMP,
            )
            for c in codes
        }

    def get_realtime_quotes(self, codes):
        assert codes == ["600001.SH"]
        return Obj(data={c: quote() for c in codes})


class Repo:
    def __init__(self):
        self.saved = []
        self.members = None

    def latest_cn_trend_ranks(self, codes):
        return {}

    def save(self, *args, **kwargs):
        pytest.fail("Preview must not save official data")

    def history(self, end, limit):
        assert end == DAYS[-2]
        return [
            {
                "trade_date": DAYS[-offset - 1],
                "industry_code": "000000.TI",
                "strength_rank": 10 + offset,
                "strength_score": 80,
            }
            for offset in (1, 3, 5)
        ]

    def latest_cn_trend_date(self):
        return DAYS[-2]


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    from finance_analysis.industry_strength import service

    monkeypatch.setattr(module, "get_market_now", lambda *a: STAMP)
    monkeypatch.setattr(module, "is_market_open", lambda *a: True)
    monkeypatch.setattr(service, "get_market_now", lambda *a: STAMP)
    monkeypatch.setattr(service, "get_trading_days_between", lambda *a: DAYS)


def test_overlay_replaces_today_and_rebases_adjusted_history():
    bars = [Obj(trade_date=d, close=100, amount=100, volume=10) for d in DAYS]
    result = overlay(bars, quote(66, pre_close=60), DAY, DAYS[-2], stock=True)
    assert len(result) == 21
    assert result[-1].close == 66
    assert result[-2].close == 60
    assert bars[-2].close == 100
    assert len(overlay(bars, quote(stamp=STAMP - timedelta(days=1)), DAY, DAYS[-2])) == 20


def test_preview_refetches_full_inputs_updates_benchmark_and_only_caches_results():
    repo, data, cache = Repo(), Data(), PreviewCache(Redis())
    service = IndustryPreviewService(repo, data, cache=cache)
    service.run_preview()
    first = cache.read()["result"]
    assert len(first["items"]) == 20
    row = first["items"][0]
    assert row["rank_change_1d"] == 10
    assert row["rank_change_3d"] == 12
    assert row["rank_change_5d"] == 14
    assert first["constituents"]["000000.TI"]["items"][0]["change_pct"] == pytest.approx(0.25)
    assert first["constituents"]["000000.TI"]["items"][0]["above_ma20"] is True
    assert repo.saved == [] and repo.members is None
    assert data.history_calls == 21
    assert len(data.stock_calls) == 1
    data.benchmark_price = 130
    service.run_preview()
    second = cache.read()["result"]
    assert second["items"][0]["rs_5d"] < row["rs_5d"]
    assert second["items"][0]["rank_change_3d"] == 12
    assert data.history_calls == 42 and len(data.stock_calls) == 2
    assert data.catalog_calls == 2 and data.member_calls == 40
    assert set(cache.client.values) == {module.KEY}
    PreviewResponse.model_validate(cache.read())
    data.stale_benchmark = True
    with pytest.raises(ValueError, match="benchmark not ready"):
        service.run_preview()
    failed = cache.read()
    assert failed["status"] == "failed"
    assert failed["result"] == second
    assert failed["error"]
    assert repo.saved == []


@pytest.mark.parametrize("opened,hour", [(False, 11), (True, 9)])
def test_only_current_open_session(monkeypatch, opened, hour):
    monkeypatch.setattr(module, "is_market_open", lambda *a: opened)
    monkeypatch.setattr(module, "get_market_now", lambda *a: STAMP.replace(hour=hour, minute=0))
    with pytest.raises(ValueError, match="开盘后"):
        module.current_day()


def test_missing_adjustment_anchor_does_not_invent_ma():
    bars = [Obj(trade_date=d, close=100, amount=100, volume=10) for d in DAYS]
    result = overlay(bars, quote(pre_close=None), DAY, DAYS[-2], stock=True)
    assert len(result) == 1


def test_http_drops_yesterday_and_never_calculates(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints.industry_strength import preview

    cache = PreviewCache(Redis())
    cache.write({"status": "completed", "result": {"trade_date": (DAY - timedelta(days=1)).isoformat()}})
    monkeypatch.setattr(module, "PreviewCache", lambda: cache)
    from finance_analysis.market_review import trading_calendar

    monkeypatch.setattr(trading_calendar, "get_market_now", lambda *a: STAMP)
    assert preview()["result"] is None


def test_preview_has_no_manual_http_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import industry_strength as endpoint
    from finance_analysis.interfaces.api import deps

    app = FastAPI()
    app.include_router(endpoint.router, prefix="/industry")
    app.dependency_overrides[deps.require_current_user] = lambda: Obj(id=7, role="admin")
    with TestClient(app) as client:
        assert client.post("/industry/preview/run").status_code in (404, 405)


def test_task_center_cannot_submit_preview():
    from finance_analysis.tasks.service import ScheduledTaskService, ManualRunNotAllowedError

    service = object.__new__(ScheduledTaskService)
    with pytest.raises(ManualRunNotAllowedError):
        service.run_scheduled_task_now(job_id="industry_strength_preview_cn", triggered_by_uid=7)


def test_next_run_recovers_after_upstream_history_is_repaired():
    data, cache = Data(), PreviewCache(Redis())
    service = IndustryPreviewService(Repo(), data, cache=cache)
    data.incomplete_history = True
    with pytest.raises(ValueError, match="benchmark not ready"):
        service.run_preview()
    assert cache.read()["status"] == "failed"
    data.incomplete_history = False
    service.run_preview()
    assert cache.read()["status"] == "completed"
    assert data.history_calls == 22
    assert set(cache.client.values) == {module.KEY}


def test_preview_and_formal_calculations_match_for_identical_daily_inputs():
    from finance_analysis.industry_strength.service import IndustryStrengthService

    data = Data()

    def index_quotes(codes):
        return {code: Obj(**{**vars(quote(120)), "amount": 100, "volume": 10}) for code in codes}

    def stock_quotes(codes):
        return {code: Obj(**{**vars(quote(100, pre_close=100)), "amount": 100, "volume": 10}) for code in codes}

    data.get_index_quotes = index_quotes
    data.get_realtime_quotes = lambda codes: Obj(data=stock_quotes(codes))
    # Formal includes today's stored bar; Preview replaces it with the identical live bar.
    service = IndustryStrengthService(Repo(), data)
    data.stock_history_end = DAY
    formal, formal_members, _ = service.calculate(DAY, False)
    data.stock_history_end = DAYS[-2]
    preview, preview_members, _ = service.calculate(DAY, False, preview=True)
    for official, intraday in zip(formal, preview):
        assert {k: v for k, v in official.items() if k != "members_observed_at"} == {
            k: v for k, v in intraday.items() if k != "members_observed_at"
        }
    assert formal_members == preview_members
