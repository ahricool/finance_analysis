from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.trend_following.models import UniverseMember
from finance_analysis.trend_following.service import TrendFollowingService

TRADE_DATE = date(2026, 8, 28)


class FakeRepository:
    market = "US"

    def __init__(self, *, benchmark_ready=True):
        self.benchmark_ready = benchmark_ready
        self.previous_requested = None
        self.snapshots = []
        self.summary = None

    def latest_daily_date(self, code):
        assert code == "SPY.US"
        return TRADE_DATE

    def daily_codes_on_date(self, codes, trade_date):
        assert trade_date == TRADE_DATE
        return set(codes) if self.benchmark_ready or "SPY.US" not in codes else set()

    def load_daily_history(self, codes, trade_date, *, calendar_lookback_days):
        assert codes == {"AAA.US", "BBB.US", "SPY.US"}
        assert calendar_lookback_days > 120
        result = []
        for symbol_id, code, step in ((1, "AAA.US", 1.2), (2, "BBB.US", 0.5), (3, "SPY.US", 0.7)):
            for index in range(80):
                close = 100 + index * step
                result.append({
                    "symbol_id": symbol_id, "code": code, "name": code,
                    "trade_date": trade_date - timedelta(days=79 - index), "open": close - 0.5,
                    "high": close + 1, "low": close - 1, "close": close, "volume": 1_000 + index * 100,
                    "amount": None,
                })
        return result

    def previous_snapshots(self, trade_date, codes):
        self.previous_requested = (trade_date, set(codes))
        return {}

    def upsert_snapshots(self, snapshots):
        self.snapshots = snapshots
        return len(snapshots)

    def upsert_summary(self, summary):
        self.summary = summary


def test_service_reads_repository_only_and_persists_point_in_time(monkeypatch):
    repository = FakeRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(TRADE_DATE)
    assert result["status"] == "completed"
    assert result["snapshot_count"] == 2
    assert repository.previous_requested == (TRADE_DATE, {"AAA.US", "BBB.US"})
    assert all(item["trade_date"] == TRADE_DATE for item in repository.snapshots)
    json.dumps(repository.summary["features"])
    for item in repository.snapshots:
        json.dumps(item["features"])
        json.dumps(item["score_breakdown"])
    forbidden = {"uid", "user_id", "account_id", "position_id", "user_cost", "user_weight", "user_pnl"}
    assert all(not forbidden.intersection(item) for item in repository.snapshots)


def test_missing_benchmark_degrades_without_fetching(monkeypatch):
    repository = FakeRepository(benchmark_ready=False)
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(TRADE_DATE)
    assert result["status"] == "incomplete"
    assert result["snapshot_count"] == 0
    assert "benchmark" in result["warnings"][-1]


def test_domain_has_no_strategy_portfolio_or_external_provider_imports():
    root = Path(PROJECT_ROOT) / "src" / "finance_analysis" / "trend_following"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (
        "finance_analysis.quant", "finance_analysis.etf_rotation", "PortfolioService", "PositionRepository",
        "yfinance", "akshare", "requests", "httpx", "market_data.providers",
    )
    for name in forbidden:
        assert name not in source
