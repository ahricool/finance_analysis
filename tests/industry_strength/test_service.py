from datetime import datetime, date, timedelta, timezone
from types import SimpleNamespace as Obj

import pytest
from finance_analysis.industry_strength import service as module
from finance_analysis.industry_strength.service import IndustryStrengthService, IndustryReadinessError

DAY = date(2026, 9, 16)
DAYS = [DAY - timedelta(days=i) for i in range(20, -1, -1)]


class Repository:
    def __init__(self):
        self.saved = []
        self.members = None
        self.trend_calls = []
        self.ranks = {}
        self.catalog = [{"thscode": f"{i:06d}.TI", "name": str(i),
                         "members_observed_at": datetime(2026, 9, 13, tzinfo=timezone.utc)} for i in range(20)]
        self.memberships = {r["thscode"]: [{"thscode": "600001.SH", "name": "共同成分"}] for r in self.catalog}

    def reference_data(self, *, include_members=True):
        return self.catalog, self.memberships

    def ranking(self, day):
        return []

    def history(self, end, limit):
        return []

    def latest_cn_trend_ranks(self, codes):
        self.trend_calls.append(codes)
        return self.ranks

    def save(self, day, rows, constituents=None):
        self.saved.append((day, rows))
        if constituents is not None:
            self.members = constituents


class MarketData:
    def __init__(self, broken=0, stale=False, partial_stock=False):
        self.broken = broken
        self.stale = stale
        self.partial_stock = partial_stock
        self.stock_calls = []

    def get_industry_catalog(self):
        return [{"thscode": f"{i:06d}.TI", "name": str(i)} for i in range(20)]

    def get_index_history(self, code, start, end):
        if code.endswith("TI") and int(code[:6]) < self.broken:
            raise ValueError("missing day")
        days = DAYS[:-1] if self.stale and code == "000300.SH" else DAYS
        return [Obj(trade_date=d, close=100 + i, amount=100, volume=10) for i, d in enumerate(days)], datetime.now(
            timezone.utc
        )

    def get_index_constituents(self, code):
        return [{"thscode": "600001.SH", "name": "共同成分"}]

    def get_daily_bars(self, codes, start, end, **kwargs):
        self.stock_calls.append((codes, kwargs))
        rows = [Obj(trade_date=d, close=100, amount=100, volume=10) for d in DAYS]
        if self.partial_stock and kwargs["source_policy"] == "db_only":
            rows = rows[-2:]
        return Obj(data={"600001.SH": rows}, request_errors={})


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr(module, "is_market_open", lambda *a: True)
    monkeypatch.setattr(module, "get_completed_trading_days", lambda *a: [DAY])
    monkeypatch.setattr(module, "get_market_now", lambda *a: datetime(2026, 9, 16, 19, tzinfo=timezone.utc))
    monkeypatch.setattr(module, "get_trading_days_between", lambda *a: DAYS)


def test_complete_run_deduplicates_stock_batch_and_does_not_invent_history():
    repo, data = Repository(), MarketData()
    result = IndustryStrengthService(repo, data).run()
    assert result["industries"] == 20
    assert len(data.stock_calls) == 1 and data.stock_calls[0][0] == ["600001.SH"]
    rows = repo.saved[0][1]
    assert sorted(r["strength_rank"] for r in rows) == list(range(1, 21))
    assert all(r["rank_change_3d"] is None for r in rows)
    assert rows[0]["quality"]["member_codes"] == ["600001.SH"]


@pytest.mark.parametrize("broken,allowed", [(1, True), (2, False)])
def test_coverage_boundary_and_atomic_publish(broken, allowed):
    repo = Repository()
    service = IndustryStrengthService(repo, MarketData(broken=broken))
    if allowed:
        assert service.run()["industries"] == 19
        assert repo.saved[0][1][0]["quality"]["coverage"] == 0.95
    else:
        with pytest.raises(IndustryReadinessError, match="no snapshot written"):
            service.run()
        assert repo.saved == []


def test_stale_benchmark_blocks_all_publication():
    repo = Repository()
    with pytest.raises(IndustryReadinessError, match="benchmark not ready"):
        IndustryStrengthService(repo, MarketData(stale=True)).run()
    assert repo.saved == []


def test_fresh_short_stock_history_reuses_database_without_remote_requests():
    repo, data = Repository(), MarketData(partial_stock=True)
    IndustryStrengthService(repo, data).run()
    assert [call[1]["source_policy"] for call in data.stock_calls] == ["db_only"]
    assert len(repo.saved) == 1
    assert repo.saved[0][1][0]["above_ma20_ratio"] is None


def test_incomplete_breadth_does_not_reject_publication():
    repo, data = Repository(), MarketData()
    data.get_daily_bars = lambda *a, **kw: Obj(data={}, request_errors={})
    result = IndustryStrengthService(repo, data).run()
    assert result["industries"] == 20
    assert all(r["up_ratio"] is None and r["above_ma20_ratio"] is None for r in repo.saved[0][1])
    assert all(r["quality"]["breadth_status"] == "partial" for r in repo.saved[0][1])


def test_current_members_are_not_used_to_backfill_previous_day(monkeypatch):
    monkeypatch.setattr(module, "get_market_now", lambda *a: datetime(2026, 9, 17, 10, tzinfo=timezone.utc))
    repo = Repository()
    with pytest.raises(IndustryReadinessError, match="no historical backfill"):
        IndustryStrengthService(repo, MarketData()).run()
    assert repo.saved == []


def test_sixty_percent_ma20_coverage_still_ranks_every_industry():
    repo, data = Repository(), MarketData()
    repo.memberships = {r["thscode"]: [{"thscode": str(i), "name": str(i)} for i in range(5)] for r in repo.catalog}
    full = [Obj(trade_date=d, close=100 + i, amount=100, volume=10) for i, d in enumerate(DAYS)]
    data.get_daily_bars = lambda *a, **kw: Obj(data={str(i): full if i < 3 else full[-10:] for i in range(5)})
    assert IndustryStrengthService(repo, data).run()["industries"] == 20
    for row in repo.saved[0][1]:
        assert row["strength_rank"] is not None
        assert row["quality"]["ma20_coverage"] == .6
        assert row["quality"]["daily_breadth_coverage"] == row["quality"]["ma5_coverage"] == 1
        assert row["above_ma20_ratio"] is None
        assert row["up_ratio"] == row["above_ma5_ratio"] == 1
        assert row["ma20_valid_count"] == row["above_ma20_count"] == 3


def test_calculation_never_requests_catalog_or_constituents():
    repo, data = Repository(), MarketData()
    def fail(code):
        raise module.FuyaoError("upstream unavailable")
    data.get_industry_catalog = fail
    data.get_index_constituents = fail
    assert IndustryStrengthService(repo, data).run()["industries"] == 20
    assert repo.saved[0][1][0]["members_observed_at"] == repo.catalog[0]["members_observed_at"]


def test_failed_remote_history_preserves_usable_short_stored_window():
    data = MarketData()
    short = [Obj(trade_date=d, close=100, amount=100, volume=10) for d in DAYS[-10:]]
    data.get_daily_bars = lambda *a, **kw: Obj(data={"600001.SH": short} if kw["source_policy"] == "db_only" else {})
    result = IndustryStrengthService(Repository(), data).load_member_history(["600001.SH"], DAYS)
    assert len(result["600001.SH"]) == 10


def test_explicit_historical_run_saves_index_only_without_current_members(monkeypatch):
    monkeypatch.setattr(module, "get_market_now", lambda *a: datetime(2026, 9, 17, 2, tzinfo=timezone.utc))
    repo, data = Repository(), MarketData()
    def no_members(code):
        raise AssertionError("Historical backfill must not read current constituents")
    data.get_index_constituents = no_members
    assert IndustryStrengthService(repo, data).run(DAY)["industries"] == 20
    assert data.stock_calls == []
    for row in repo.saved[0][1]:
        assert row["members_observed_at"] is None
        assert row["up_ratio"] is None and row["constituent_count"] is None
        assert row["quality"]["breadth_status"] == "unavailable_historical_members"
        assert row["strength_rank"] is not None


@pytest.mark.parametrize("closed", [True, False])
def test_rejects_future_or_nontrading_dates(monkeypatch, closed):
    repo = Repository()
    monkeypatch.setattr(module, "is_market_open", lambda *a: closed)
    with pytest.raises(IndustryReadinessError, match="completed trading session"):
        IndustryStrengthService(repo, MarketData()).run(DAY + timedelta(days=1) if closed else DAY)
    assert not repo.saved


def test_historical_backfill_preserves_existing_observed_breadth(monkeypatch):
    monkeypatch.setattr(module, "get_market_now", lambda *a: datetime(2026, 9, 17, 2, tzinfo=timezone.utc))
    repo = Repository()
    repo.ranking = lambda day: [{"members_observed_at": datetime.now(timezone.utc)}]
    with pytest.raises(IndustryReadinessError, match="must not be overwritten"):
        IndustryStrengthService(repo, MarketData()).run(DAY)
    assert not repo.saved


@pytest.mark.parametrize("ranks,expected", [({"600001.SH": 38}, 38), ({"600002.SH": 1}, None), ({}, None)])
def test_materializes_observations_with_one_deduplicated_trend_query(ranks, expected):
    repo, data = Repository(), MarketData()
    repo.ranks = ranks
    assert IndustryStrengthService(repo, data).run()["status"] == "completed"
    assert repo.trend_calls == [["600001.SH"]]
    assert len(repo.members) == 20
    assert {row["industry_code"] for row in repo.members} == {f"{i:06d}.TI" for i in range(20)}
    for item in repo.members:
        assert item == {
            "industry_code": item["industry_code"], "stock_code": "600001.SH", "stock_name": "共同成分",
            "price": 100, "change_pct": 0, "volume": 10, "amount": 100,
            "above_ma5": False, "above_ma20": False, "trend_rank": expected,
        }


def test_trend_read_failure_is_not_a_publication_dependency():
    from sqlalchemy.exc import OperationalError
    repo = Repository()
    def fail(codes):
        raise OperationalError("SELECT", {}, Exception("unavailable"))
    repo.latest_cn_trend_ranks = fail
    assert IndustryStrengthService(repo, MarketData()).run()["status"] == "completed"
    assert all(item["trend_rank"] is None for item in repo.members)


def test_failure_and_historical_backfill_preserve_latest_members(monkeypatch):
    repo = Repository()
    IndustryStrengthService(repo, MarketData()).run()
    previous = repo.members
    with pytest.raises(IndustryReadinessError):
        IndustryStrengthService(repo, MarketData(broken=2)).run()
    assert repo.members is previous
    monkeypatch.setattr(module, "get_market_now", lambda *a: datetime(2026, 9, 17, 2, tzinfo=timezone.utc))
    IndustryStrengthService(repo, MarketData()).run(DAY)
    assert repo.members is previous
    assert repo.trend_calls == [["600001.SH"]]


@pytest.mark.parametrize("sessions", [DAYS, DAYS[:-1]])
def test_latest_session_is_the_only_remote_fetch_trigger(sessions):
    code = "600001.SH"
    data = MarketData()
    short = [Obj(trade_date=d, close=100, amount=100, volume=10) for d in sessions[-2:]]
    calls = []
    def read(codes, start, end, **kwargs):
        calls.append((codes, start, end, kwargs))
        return Obj(data={code: short})
    data.get_daily_bars = read
    result = IndustryStrengthService(Repository(), data).load_member_history([code], sessions)
    assert result[code] == short
    assert len(calls) == 1 and calls[0][3]["source_policy"] == "db_only"
    assert calls[0][2] == sessions[-1]


def test_only_stale_stocks_fetch_remote_with_required_target_date():
    fresh, stale = "600001.SH", "600002.SH"
    db_bars = [Obj(trade_date=d, close=100) for d in DAYS]
    remote_bars = [Obj(trade_date=d, close=120) for d in DAYS]
    calls = []
    def read(codes, start, end, **kwargs):
        calls.append((codes, kwargs))
        return Obj(data={fresh: db_bars, stale: db_bars[:-1]} if kwargs["source_policy"] == "db_only"
                   else {stale: remote_bars})
    result = IndustryStrengthService(Repository(), Obj(get_daily_bars=read)).load_member_history([fresh, stale], DAYS)
    assert calls[1] == ([stale], {"adjustment": "forward", "source_policy": "remote_only", "required_dates": (DAY,)})
    assert result[fresh] == db_bars and result[stale] == remote_bars


@pytest.mark.parametrize("failure", [True, False])
def test_failed_or_stale_remote_does_not_replace_usable_database_history(failure):
    short = [Obj(trade_date=d, close=100) for d in DAYS[-11:-1]]
    def read(codes, start, end, **kwargs):
        if kwargs["source_policy"] == "db_only":
            return Obj(data={"600001.SH": short})
        if failure:
            raise RuntimeError("source unavailable")
        return Obj(data={"600001.SH": short[-2:]})
    result = IndustryStrengthService(Repository(), Obj(get_daily_bars=read)).load_member_history(["600001.SH"], DAYS)
    assert result["600001.SH"] == short


def test_overlapping_industries_compute_stock_observations_once_and_preserve_reference_names(monkeypatch):
    repo = Repository()
    repo.memberships["000000.TI"][0]["name"] = "行业内名称"
    real = module.constituent_observations
    calls = []
    def observe(members, stocks, sessions):
        calls.append([m["thscode"] for m in members])
        return real(members, stocks, sessions)
    monkeypatch.setattr(module, "constituent_observations", observe)
    IndustryStrengthService(repo, MarketData()).run()
    assert calls == [["600001.SH"]]
    assert next(m for m in repo.members if m["industry_code"] == "000000.TI")["stock_name"] == "行业内名称"
