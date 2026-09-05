from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from finance_analysis.trend_following.config import DEFAULT_CONFIG  # pragma: allowlist secret
from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.trend_following.models import UniverseMember
from finance_analysis.trend_following.service import TrendFollowingService as RealTrendFollowingService

TRADE_DATE = date(2026, 8, 24)


def TrendFollowingService(market, repository, **kwargs):
    class MarketData:
        def get_daily_bars(self, codes, start, end, **options):
            assert codes == ["SPY.US"]  # the main universe must never fall back
            assert options == {"adjustment": "forward", "source_policy": "db_fresh"}
            if not repository.benchmark_ready or end == getattr(repository, "incomplete_date", None):
                return SimpleNamespace(data={})
            rows = repository.load_daily_history({"AAA.US", "BBB.US"}, end, calendar_lookback_days=500)
            return SimpleNamespace(data={"SPY.US": [SimpleNamespace(**row) for row in rows if row["code"] == "SPY.US"]})

    kwargs.setdefault("market_data", MarketData())
    return RealTrendFollowingService(market, repository, **kwargs)


@pytest.fixture(autouse=True)
def _completed_day(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_completed_trading_days",
        lambda *_args: [TRADE_DATE + timedelta(days=3)],
    )


class FakeRepository:
    market = "US"

    def __init__(self, *, benchmark_ready=True):
        self.benchmark_ready = benchmark_ready
        self.previous_requested = None
        self.previous_calls = []
        self.upserted_dates = []
        self.invalidated_dates = []
        self.snapshots = []
        self.summary = None

    def latest_daily_date(self, code):
        assert code == "SPY.US"
        return TRADE_DATE

    def daily_codes_on_date(self, codes, trade_date):
        return set(codes) if self.benchmark_ready or "SPY.US" not in codes else set()

    def load_daily_history(self, codes, trade_date, *, calendar_lookback_days):
        assert codes == {"AAA.US", "BBB.US"}
        assert calendar_lookback_days > 120
        result = []
        for instrument_id, code, step in ((1, "AAA.US", 1.2), (2, "BBB.US", 0.5), (3, "SPY.US", 0.7)):
            for index in range(80):
                close = 100 + index * step
                result.append(
                    {
                        "instrument_id": instrument_id,
                        "code": code,
                        "name": code,
                        "trade_date": trade_date - timedelta(days=79 - index),
                        "open": close - 0.5,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1_000 + index * 100,
                        "amount": None,
                    }
                )
        return result

    def previous_snapshots(self, trade_date, codes):
        self.previous_requested = (trade_date, set(codes))
        self.previous_calls.append((trade_date, set(codes)))
        return {}

    def latest_snapshot_date(self):
        return None

    def latest_trade_date(self):
        return None

    def daily_dates_between(self, code, start, end):
        return [start]

    def snapshot_dates_between(self, start, end):
        return []

    def upsert_snapshots(self, snapshots):
        self.snapshots = snapshots
        self.upserted_dates.append(snapshots[0]["trade_date"] if snapshots else None)
        return len(snapshots)

    def upsert_summary(self, summary):
        self.summary = summary

    def replace_day(self, trade_date, snapshots, summary):
        self.snapshots = snapshots
        self.summary = summary
        self.upserted_dates.append(trade_date)
        return len(snapshots)

    def invalidate_from(self, trade_date):
        self.invalidated_dates.append(trade_date)


def test_service_reads_repository_only_and_persists_point_in_time(monkeypatch):
    repository = FakeRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
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
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
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
        "finance_analysis.quant",
        "finance_analysis.etf_rotation",
        "yfinance",
        "akshare",
        "requests",
        "httpx",
        "market_data.providers",
    )
    for name in forbidden:
        assert name not in source


class RebuildRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.future = date(2026, 8, 31)
        self.states = {}

    def latest_snapshot_date(self):
        return self.future

    def daily_dates_between(self, code, start, end):
        assert code == "SPY.US"
        return [start, end]

    def snapshot_dates_between(self, start, end):
        return [start, date(2026, 8, 29), self.future]

    def previous_snapshots(self, trade_date, codes):
        self.previous_calls.append((trade_date, set(codes)))
        assert all(item <= trade_date for item in [trade_date])
        return {code: payload for code, payload in self.states.items() if payload["trade_date"] < trade_date}

    def replace_day(self, trade_date, snapshots, summary):
        for item in snapshots:
            self.states[item["code"]] = item
        return super().replace_day(trade_date, snapshots, summary)


def test_historical_rerun_rebuilds_future_dates_in_order(monkeypatch):
    repository = RebuildRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(TRADE_DATE)
    assert result["rebuild_count"] == 6
    assert repository.upserted_dates == [
        TRADE_DATE,
        date(2026, 8, 25),
        date(2026, 8, 26),
        date(2026, 8, 27),
        date(2026, 8, 28),
        date(2026, 8, 31),
    ]
    assert [item[0] for item in repository.previous_calls] == repository.upserted_dates
    assert all(call[0] <= TRADE_DATE or True for call in repository.previous_calls)
    assert all(call[0] < date(2026, 9, 1) and call[0] >= TRADE_DATE for call in repository.previous_calls)


def test_signal_day_snapshots_do_not_assume_same_day_fill(monkeypatch):
    repository = FakeRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    TrendFollowingService("US", repository).run(TRADE_DATE)
    for item in repository.snapshots:
        if item["state"] == "CANDIDATE":
            assert item["units"] == 0
            assert item["entry_price"] is None
            assert item["opened_at"] is None
            assert item["signal_date"] == TRADE_DATE
        if item["action"] == "ENTRY":
            raise AssertionError("signal day must not produce a same-session ENTRY")


class LatestRecoveryRepository(FakeRepository):
    def __init__(self, *, incomplete_date=None):
        super().__init__()
        self.snapshot_date = TRADE_DATE
        self.raw_date = TRADE_DATE + timedelta(days=3)
        self.incomplete_date = incomplete_date

    def latest_daily_date(self, code):
        assert code == "SPY.US"
        return self.raw_date

    def latest_snapshot_date(self):
        return self.snapshot_date

    def daily_dates_between(self, code, start, end):
        assert code == "SPY.US"
        return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    def daily_codes_on_date(self, codes, trade_date):
        if "SPY.US" in codes and trade_date == self.incomplete_date:
            return set()
        return set(codes)


def test_run_latest_recovers_missing_benchmark_trading_dates_in_order(monkeypatch):
    repository = LatestRecoveryRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(None)
    assert result["rebuild_status"] == "completed"
    assert repository.upserted_dates == [
        TRADE_DATE + timedelta(days=1),
        TRADE_DATE + timedelta(days=2),
        TRADE_DATE + timedelta(days=3),
    ]


def test_rebuild_stops_immediately_when_an_intermediate_date_is_incomplete(monkeypatch):
    stopped_at = TRADE_DATE + timedelta(days=2)
    repository = LatestRecoveryRepository(incomplete_date=stopped_at)
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(None)
    assert result["status"] == "incomplete"
    assert result["rebuild_status"] == "stopped"
    assert result["rebuild_stopped_at"] == stopped_at.isoformat()
    assert repository.upserted_dates == [TRADE_DATE + timedelta(days=1)]


class MissingActiveRepository(FakeRepository):
    def __init__(self, pending_action=None):
        super().__init__()
        self.pending_action = pending_action

    def daily_codes_on_date(self, codes, trade_date):
        if "SPY.US" in codes:
            return {"SPY.US"}
        return {"BBB.US"}

    def previous_snapshots(self, trade_date, codes):
        return {
            "AAA.US": {
                "market": "US",
                "trade_date": trade_date - timedelta(days=1),
                "code": "AAA.US",
                "universe_key": "us_trend",
                "market_regime": "RISK_ON",
                "market_score": 80.0,
                "rank": 1,
                "trend_score": 80.0,
                "rs_score": 80.0,
                "breakout_score": 80.0,
                "alpha_score": 90.0,
                "features": {},
                "score_breakdown": {},
                "setup": "BREAKOUT_20D",
                "state": "HOLDING",
                "action": "HOLD",
                "reference_price": 110.0,
                "atr": 2.0,
                "entry_price": 100.0,
                "last_add_price": 100.0,
                "highest_close": 110.0,
                "initial_stop": 96.0,
                "trailing_stop": 105.0,
                "next_add_price": 111.0,
                "exit_level": 105.0,
                "units": 1,
                "opened_at": trade_date - timedelta(days=5),
                "suggested_initial_weight": 0.1,
                "suggested_max_weight": 0.1,
                "reasons": ["holding"],
                "pending_action": self.pending_action,
                "pending_since": trade_date - timedelta(days=1) if self.pending_action else None,
                "pending_regime": "RISK_ON" if self.pending_action else None,
                "pending_max_exposure": 1.0 if self.pending_action else None,
            }
        }


def test_missing_active_code_is_carried_forward_without_changing_risk(monkeypatch):
    repository = MissingActiveRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    config = replace(DEFAULT_CONFIG, minimum_data_coverage=0.5)
    result = TrendFollowingService("US", repository, config=config).run(TRADE_DATE)
    assert result["status"] == "completed"
    carried = next(item for item in repository.snapshots if item["code"] == "AAA.US")
    assert (carried["state"], carried["action"], carried["units"]) == ("HOLDING", "HOLD", 1)
    assert carried["initial_stop"] == 96.0
    assert carried["trailing_stop"] == 105.0
    assert "carried forward" in carried["reasons"][-1]


def test_explicit_future_run_recovers_intermediate_benchmark_sessions(monkeypatch):
    repository = LatestRecoveryRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(repository.raw_date)
    assert result["rebuild_status"] == "completed"
    assert repository.upserted_dates == [
        TRADE_DATE + timedelta(days=1),
        TRADE_DATE + timedelta(days=2),
        TRADE_DATE + timedelta(days=3),
    ]


class HistoricalFailureRepository(LatestRecoveryRepository):
    def __init__(self):
        super().__init__(incomplete_date=TRADE_DATE + timedelta(days=1))
        self.snapshot_date = TRADE_DATE + timedelta(days=3)

    def latest_snapshot_date(self):
        return self.snapshot_date


def test_historical_failure_invalidates_the_remaining_future_chain(monkeypatch):
    repository = HistoricalFailureRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    result = TrendFollowingService("US", repository).run(TRADE_DATE)
    assert result["rebuild_status"] == "stopped"
    assert result["rebuild_stopped_at"] == (TRADE_DATE + timedelta(days=1)).isoformat()
    assert repository.upserted_dates == [TRADE_DATE]
    assert repository.invalidated_dates == [TRADE_DATE + timedelta(days=1)]


def test_historical_exception_also_invalidates_the_remaining_future_chain(monkeypatch):
    repository = HistoricalFailureRepository()
    service = TrendFollowingService("US", repository)
    failed_at = TRADE_DATE + timedelta(days=1)

    def run_date(trade_date):
        if trade_date == TRADE_DATE:
            return {"status": "completed", "trade_date": trade_date.isoformat()}
        raise RuntimeError("calculation failed")

    monkeypatch.setattr(service, "_run_single_date", run_date)
    result = service.run(TRADE_DATE)
    assert result["status"] == "failed"
    assert result["rebuild_stopped_at"] == failed_at.isoformat()
    assert repository.invalidated_dates == [failed_at]


@pytest.mark.parametrize("pending_action", ["EXIT", "REDUCE"])
def test_missing_data_preserves_pending_risk_reduction(monkeypatch, pending_action):
    repository = MissingActiveRepository(pending_action)
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    config = replace(DEFAULT_CONFIG, minimum_data_coverage=0.5)
    TrendFollowingService("US", repository, config=config).run(TRADE_DATE)
    carried = next(item for item in repository.snapshots if item["code"] == "AAA.US")
    assert carried["pending_action"] == pending_action
    assert carried["pending_regime"] == "RISK_ON"
    assert "preserved" in carried["reasons"][-1]


def test_missing_data_expires_pending_add(monkeypatch):
    repository = MissingActiveRepository("ADD")
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    config = replace(DEFAULT_CONFIG, minimum_data_coverage=0.5)
    TrendFollowingService("US", repository, config=config).run(TRADE_DATE)
    carried = next(item for item in repository.snapshots if item["code"] == "AAA.US")
    assert carried["pending_action"] is None
    assert "expired" in carried["reasons"][-1]


def test_cn_trend_batches_csi2000_history_before_readiness_without_daily_writes(monkeypatch):
    codes = {"600001.SH", "600002.SH", "600003.SH"}
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",
        lambda market: [UniverseMember(market, code, code) for code in sorted(codes)],
    )
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.UniverseResolver",
        lambda: SimpleNamespace(
            resolve_universe=lambda key: [SimpleNamespace(code=code) for code in sorted(codes - {"600001.SH"})]
        ),
    )
    calls = []

    def bars(code):
        return [
            SimpleNamespace(
                trade_date=TRADE_DATE - timedelta(days=79 - i),
                open=100 + i,
                high=102 + i,
                low=99 + i,
                close=101 + i,
                volume=1000 + i,
                amount=None,
            )
            for i in range(80)
        ]

    def fetch(requested, start, end, **options):
        calls.append((requested, start, end, options))
        return SimpleNamespace(data={code: bars(code) for code in requested})

    class Repository(FakeRepository):
        market = "CN"

        def daily_codes_on_date(self, requested, day):
            assert requested == {"600001.SH"}
            return set(requested)

        def load_daily_history(self, requested, day, **kwargs):
            assert requested == {"600001.SH"}
            return [dict(code="600001.SH", **vars(bar)) for bar in bars("600001.SH")]

    repository = Repository()
    result = RealTrendFollowingService("CN", repository, market_data=SimpleNamespace(get_daily_bars=fetch)).run(
        TRADE_DATE
    )
    assert result["status"] == "completed"
    assert result["data_ready_count"] == 3
    assert calls[0][0] == ["600002.SH", "600003.SH"]
    assert calls[1][0] == ["510300.SH"]
    assert all(call[3] == {"adjustment": "forward", "source_policy": "db_fresh"} for call in calls)
    assert calls[0][1] == TRADE_DATE - timedelta(days=DEFAULT_CONFIG.calendar_lookback_days)
