"""Rolling RSI and per-period preview failures use isolated, point-in-time state."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from finance_analysis.analysis.technical.indicators import rsi_series
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.mean_reversion import calculate_mean_reversion
from finance_analysis.trend_following.models import DailyBar, UniverseMember
from finance_analysis.trend_following.preview_cache import load_preview, save_preview
from finance_analysis.trend_following.service import TrendFollowingService
from finance_analysis.tasks.celery.jobs.trend_following import tasks

DAY = date(2026, 10, 12)


@pytest.mark.parametrize("period", [20, 40, 60])
def test_rolling_rsi_uses_one_seed_and_preserves_consumed_episode(period):
    config = replace(DEFAULT_CONFIG, trend_period=period)
    size = config.history_bars
    prices = [200, 210, *[210 - i for i in range(1, size - 1)]]
    prices += [prices[-1] + 0.5, prices[-1] - 0.5, prices[-1]]
    bars = [DailyBar(DAY + timedelta(days=i), c - 0.1, c + 0.1, c - 0.4, c, 1000) for i, c in enumerate(prices)]

    def evaluate(end, previous=None, preview=False):
        visible = bars[:end][-size:]
        features = calculate_features(visible, config=config, preview=preview)
        return calculate_mean_reversion(visible, features, config, previous_features=previous)

    prior = evaluate(size)
    assert prior["mr_state"] == "MR_OVERSOLD"
    prior_copy = deepcopy(prior)
    current = evaluate(size + 1, prior)
    cold = evaluate(size + 1)
    expected = rsi_series(pd.Series(prices[1 : size + 1]), period, wilder=True)
    assert current["mr_previous_rsi14"] == pytest.approx(expected.iloc[-2])
    assert current["rsi14"] == pytest.approx(expected.iloc[-1])
    # The removed initial jump makes yesterday's *stored* RSI larger than today's.
    # Mixing those seeds would miss this genuine within-window RSI rise.
    assert prior["rsi14"] > current["rsi14"] > current["mr_previous_rsi14"]
    assert current == cold == evaluate(size + 1, prior, preview=True)
    assert current["mr_state"] == "MR_REBOUND"
    assert current["mr_reversal_quality"] > 0
    assert current["mr_episode_consumed"] is True
    assert prior == prior_copy
    down = evaluate(size + 2, current)
    again = evaluate(size + 3, down)
    assert down["mr_state"] == "MR_OVERSOLD"
    assert again["mr_state"] != "MR_REBOUND"
    assert again["mr_episode_consumed"] is True


from tests.preview_redis import MemoryRedis

@pytest.mark.parametrize("failure", [None, 20, 40, "collection", "benchmark"])
def test_preview_round_failure_isolation_cache_replacement_and_retry(monkeypatch, failure):
    client = MemoryRedis()
    calls, calculated = [], []
    mode = {"failure": failure}
    for period in (20, 40, 60):
        save_preview("US", {"market": "US", "trade_date": DAY.isoformat(), "status": "completed", "trend_period": period, "snapshots": [{"code": "OLD.US"}]}, client=client)

    def collect(*args):
        calls.append("collect")
        if mode["failure"] == "collection":
            raise RuntimeError("shared provider unavailable")
        return {}, "test-provider", 0, None

    def calculate(self, day, *, persist, overlay_bars):
        period = self.config.trend_period
        calculated.append(period)
        assert persist is False
        self._forward_adjusted_histories({"SPY.US"}, day)
        if mode["failure"] == period:
            raise ValueError(f"period {period} calculation failed")
        return {
            "status": "completed",
            "market": "US",
            "trend_period": period,
            "trade_date": day.isoformat(),
            "snapshots": [{"code": "AAA.US", "alpha_score": period}],
        }

    benchmark_calls = []

    def benchmark(*args, **kwargs):
        benchmark_calls.append("benchmark")
        if mode["failure"] == "benchmark":
            raise RuntimeError("shared benchmark unavailable")
        return SimpleNamespace(data={})

    def service(market, *, config, input_cache):
        repo = SimpleNamespace(market=market, trend_period=config.trend_period)
        return TrendFollowingService(
            market, repo, config=config, market_data=SimpleNamespace(get_daily_bars=benchmark), input_cache=input_cache
        )

    monkeypatch.setattr(tasks, "TrendFollowingService", service)
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe", lambda _: (UniverseMember("US", "AAA.US", "AAA"),)
    )
    monkeypatch.setattr("finance_analysis.trend_following.service.collect_preview_daily_bars", collect)
    monkeypatch.setattr(TrendFollowingService, "_run_single_date", calculate)
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.save_preview",
        lambda market, payload: save_preview(market, payload, client=client),
    )

    if failure is None:
        results = tasks._run_periods("US", DAY, preview=True)["periods"]
    else:
        with pytest.raises(RuntimeError, match="Trend Following did not complete: ") as error:
            tasks._run_periods("US", DAY, preview=True)
        results = json.loads(str(error.value).split(": ", 1)[1])
    assert calls == ["collect"]
    assert benchmark_calls == ([] if failure == "collection" else ["benchmark"])
    assert calculated == ([] if failure == "collection" else [20, 40, 60])
    for period in (20, 40, 60):
        payload = load_preview("US", trend_period=period, client=client)
        failed = failure in (period, "collection", "benchmark")
        assert payload["status"] == results[str(period)]["status"] == ("failed" if failed else "completed")
        assert payload["snapshots"] == ([] if failed else [{"code": "AAA.US", "alpha_score": period}])
        assert payload["trade_date"] == DAY.isoformat()
        assert payload["trend_period"] == period
        if failed:
            assert payload["warnings"]
    # Each Celery retry owns a fresh input cache, so a failed collection isn't sticky.
    mode["failure"] = None
    result = tasks._run_periods("US", DAY, preview=True)
    assert calls == ["collect", "collect"]
    assert all(row["status"] == "completed" for row in result["periods"].values())
    for period in (20, 40, 60):
        assert load_preview("US", trend_period=period, client=client)["snapshots"] == [{"code": "AAA.US", "alpha_score": period}]


@pytest.mark.parametrize("period", [20, 40, 60])
def test_service_preview_and_official_share_rsi_without_mutating_official_state(monkeypatch, period):
    from tests.test_trend_following_preview import PreviewRepository

    config = replace(DEFAULT_CONFIG, trend_period=period)
    size = config.history_bars
    prices = [200, 210, *[210 - i for i in range(1, size - 1)]]
    prices += [prices[-1] + 0.5, 999]  # Future bar must never enter either calculation.
    history = [
        dict(
            code="AAA.US",
            trade_date=DAY + timedelta(days=i - size),
            open=c - 0.1,
            high=c + 0.1,
            low=c - 0.4,
            close=c,
            volume=1000,
            amount=None,
        )
        for i, c in enumerate(prices)
    ]
    repository = PreviewRepository()
    repository.trend_period = period
    repository.load_daily_history = lambda *args, **kwargs: history
    market_data = SimpleNamespace(
        get_daily_bars=lambda *args, **kwargs: SimpleNamespace(
            data={"SPY.US": [SimpleNamespace(**bar) for bar in history]}
        )
    )
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe", lambda _: (UniverseMember("US", "AAA.US", "AAA"),)
    )
    # The repository's data-ready query is point in time, as in production.
    service = TrendFollowingService("US", repository, config=config, market_data=market_data)
    service._run_single_date(DAY - timedelta(days=1))
    previous = deepcopy(repository.states)
    assert previous["AAA.US"]["features"]["mr_state"] == "MR_OVERSOLD"
    today = SimpleNamespace(**history[-2])
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.collect_preview_daily_bars",
        lambda *args: ({"AAA.US": today, "SPY.US": today}, "test", 2, None),
    )
    cached = []
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.save_preview", lambda market, payload: cached.append(payload)
    )
    preview = service.run_preview(DAY)
    assert repository.states == previous
    assert repository.replace_calls == [DAY - timedelta(days=1)]
    assert preview["status"] == "completed"
    service._run_single_date(DAY)
    formal = repository.states["AAA.US"]["features"]
    temporary = next(row["features"] for row in preview["snapshots"] if row["code"] == "AAA.US")
    for key in ("rsi14", "mr_previous_rsi14", "mr_state", "mr_episode_consumed", "mr_reversal_quality"):
        assert temporary[key] == formal[key]
    assert formal["mr_state"] == "MR_REBOUND"
    assert formal["reference_price"] == prices[-2]
    assert formal["trend_period"] == period
