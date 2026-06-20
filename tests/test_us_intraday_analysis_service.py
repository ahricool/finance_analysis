from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.tasks.jobs.us_intraday_analysis import (
    aggregate_bars,
    compute_intraday_metrics,
    evaluate_signal_candidates,
    is_us_market_open,
    parse_llm_json_response,
)


US_EASTERN = ZoneInfo("America/New_York")


def _bar(ts: datetime, open_price: float, close: float, volume: int = 100) -> dict:
    high = max(open_price, close) + 0.05
    low = min(open_price, close) - 0.05
    return {
        "timestamp": ts.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover": close * volume,
    }


def test_aggregate_bars_builds_5m_ohlcv():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    bars = [_bar(start + timedelta(minutes=i), 100 + i, 100.5 + i, volume=10 + i) for i in range(6)]

    result = aggregate_bars(bars, 5)

    assert len(result) == 2
    assert result[0]["timestamp"].endswith("09:30:00-04:00")
    assert result[0]["open"] == 100
    assert result[0]["close"] == 104.5
    assert result[0]["volume"] == sum(range(10, 15))
    assert result[1]["open"] == 105
    assert result[1]["close"] == 105.5


def test_evaluate_signal_candidates_detects_breakout():
    metrics = {
        "change_5m": 0.95,
        "change_15m": 1.8,
        "relative_to_qqq_15m": 0.9,
        "volume_ratio_5m": 2.4,
        "price_above_vwap": True,
        "near_intraday_high": True,
    }

    candidates = evaluate_signal_candidates(metrics)

    assert [item["signal_type"] for item in candidates] == ["relative_strength_breakout"]


def test_compute_intraday_metrics_relative_strength_and_vwap():
    start = datetime(2026, 6, 10, 9, 30, tzinfo=US_EASTERN)
    bars = []
    price = 100.0
    for i in range(70):
        next_price = price * (1.0004 if i < 55 else 1.002)
        bars.append(_bar(start + timedelta(minutes=i), price, next_price, volume=100 if i < 65 else 500))
        price = next_price

    metrics = compute_intraday_metrics(
        "NVDA",
        bars,
        quote=None,
        benchmark_metrics={"change_15m": 0.2, "first_hour_change": 0.5},
        sector_metrics={"SOXX": {"change_15m": 0.4}},
    )

    assert metrics["price"] == bars[-1]["close"]
    assert metrics["vwap"] is not None
    assert metrics["change_15m"] > 0.2
    assert metrics["relative_to_qqq_15m"] == round(metrics["change_15m"] - 0.2, 4)
    assert metrics["relative_to_sector_15m"]["SOXX"] == round(metrics["change_15m"] - 0.4, 4)
    assert metrics["volume_ratio_5m"] > 1


def test_relative_to_sectors_ignores_non_metric_entries():
    from finance_analysis.tasks.jobs.us_intraday_analysis.metrics import _relative_to_sectors

    relative = _relative_to_sectors(
        1.5,
        {
            "SOXX": {"change_15m": 0.4},
            "market_news": [{"title": "headline"}],
        },
    )

    assert relative == {"SOXX": 1.1}
    assert "market_news" not in relative


def test_parse_llm_json_response_repairs_fenced_json():
    parsed = parse_llm_json_response(
        """```json
        {
          "final_decision": "watch",
          "need_notification": true,
          "confidence": 0.7,
        }
        ```"""
    )

    assert parsed is not None
    assert parsed["final_decision"] == "watch"
    assert parsed["need_notification"] is True


def test_is_us_market_open_regular_session():
    assert is_us_market_open(datetime(2026, 6, 10, 10, 0, tzinfo=US_EASTERN)) is True
    assert is_us_market_open(datetime(2026, 6, 10, 8, 0, tzinfo=US_EASTERN)) is False
