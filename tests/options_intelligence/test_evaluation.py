from datetime import datetime, date, timezone, timedelta
import pytest
from finance_analysis.options_intelligence.evaluation import evaluate
from finance_analysis.options_intelligence.views import current_view
from finance_analysis.integrations.options.models import OptionChain
from finance_analysis.options_intelligence.engine import analyze


def test_forward_returns_benchmarks_exact_sessions_and_missing_gap():
    event = {
        "symbol": "AAPL.US",
        "occurred_at": datetime(2026, 10, 5, 21, tzinfo=timezone.utc),
        "initial_evidence": {"rv_20d": 0.2},
    }
    days = [date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)]
    bars = {
        "AAPL.US": {d: {"open": 100, "close": 101 + i, "low": 98 - i} for i, d in enumerate(days)},
        "SPY.US": {d: {"open": 200, "close": 202 + i, "low": 200} for i, d in enumerate(days)},
    }
    result = evaluate(event, bars, datetime(2026, 10, 13, 21, tzinfo=timezone.utc))
    assert result["returns"][0]["value"] == pytest.approx(0.01)
    assert result["returns"][1]["value"] == pytest.approx(0.03)
    assert result["returns"][2]["value"] == pytest.approx(0.05)
    assert result["max_adverse_5d"] == pytest.approx(-0.06)
    assert result["benchmarks"]["SPY.US"][0]["value"] == pytest.approx(0.01)
    assert result["subsequent_rv_20d"] is None
    del bars["AAPL.US"][days[1]]
    partial = evaluate(event, bars, datetime(2026, 10, 13, 21, tzinfo=timezone.utc))
    assert partial["returns"][1]["status"] == "missing"
    assert partial["returns"][1]["value"] is None


def test_realtime_read_expires_liquidity_preserves_original(observation, now, config):
    metrics = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation]), now.date(), now, [], "14:00", config
    )
    original = metrics["scores"]["liquidity_risk"]["value"]
    assert original is not None
    result = current_view(metrics, now + timedelta(minutes=10))
    assert result["scores"]["liquidity_risk"]["value"] is None
    assert result["snapshot_liquidity_score"]["value"] == original
    assert metrics["scores"]["liquidity_risk"]["value"] == original
    assert result["contracts"][0]["quote_status"] == "stale_quote"
