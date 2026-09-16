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

    def history(self, end, limit):
        return []

    def save(self, day, rows):
        self.saved.append((day, rows))


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


def test_missing_stock_history_uses_existing_provider_without_persisting():
    repo, data = Repository(), MarketData(partial_stock=True)
    IndustryStrengthService(repo, data).run()
    assert [call[1]["source_policy"] for call in data.stock_calls] == ["db_only", "remote_only"]
    assert len(repo.saved) == 1


def test_incomplete_breadth_rejects_publication():
    repo, data = Repository(), MarketData()
    data.get_daily_bars = lambda *a, **kw: Obj(data={}, request_errors={})
    with pytest.raises(IndustryReadinessError, match="Breadth daily readiness"):
        IndustryStrengthService(repo, data).run()
    assert repo.saved == []


def test_current_members_are_not_used_to_backfill_previous_day(monkeypatch):
    monkeypatch.setattr(module, "get_market_now", lambda *a: datetime(2026, 9, 17, 10, tzinfo=timezone.utc))
    repo = Repository()
    with pytest.raises(IndustryReadinessError, match="no historical backfill"):
        IndustryStrengthService(repo, MarketData()).run()
    assert repo.saved == []
