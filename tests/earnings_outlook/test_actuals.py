"""Price-only reviews: closed exact sessions, no LLM or external earnings requests."""

from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from finance_analysis.earnings_outlook.context import ContextCollector
from finance_analysis.earnings_outlook.rules import normalize_prediction, review_prediction
from .test_rules import context, raw

NOW = datetime(2026, 7, 6, 22, tzinfo=timezone.utc)


def fixture():
    c = context()
    event = NS(symbol="A.US")
    version = NS(id=42, context=c, prediction=normalize_prediction(raw(), c), target_trading_date=date(2026, 7, 6))
    market = Mock(spec=["get_daily_bars"])
    market.get_daily_bars.return_value = NS(data={"A.US": [
        NS(trade_date=date(2026, 7, 2), open=99, close=100, low=98, high=102),
        NS(trade_date=date(2026, 7, 6), open=100, close=98, low=95, high=102),
    ]})
    return event, version, market


def test_only_requests_db_daily_prices_and_ignores_missing_earnings():
    event, version, market = fixture()
    for metric in ("eps", "revenue"):
        version.prediction[metric]["consensus"] = None
    before = deepcopy(version.prediction)
    actual = ContextCollector(None, market).actual(event, version, NOW)
    market.get_daily_bars.assert_called_once_with(
        ["A.US"], date(2026, 7, 2), date(2026, 7, 6), adjustment="forward", source_policy="db_only"
    )
    review = review_prediction(version.prediction, actual, version.context)
    assert review["status"] == "completed"
    assert review["daily_return_pct"] == pytest.approx(-2)
    assert review["direction_correct"] and review["range_covered"]
    assert "eps" not in review and "revenue" not in actual and "research" not in actual
    assert before == version.prediction


def test_before_target_close_does_not_even_read_bars():
    event, version, market = fixture()
    actual = ContextCollector(None, market).actual(event, version, NOW.replace(hour=19))
    market.get_daily_bars.assert_not_called()
    assert review_prediction(version.prediction, actual, version.context)["status"] == "pending"
    assert "等待" in actual["missing_reason"]


def test_early_close_is_respected():
    event, version, market = fixture()
    version.target_trading_date = date(2026, 11, 27)
    collector = ContextCollector(None, market)
    collector.actual(event, version, datetime(2026, 11, 27, 17, 59, tzinfo=timezone.utc))
    market.get_daily_bars.assert_not_called()
    collector.actual(event, version, datetime(2026, 11, 27, 18, tzinfo=timezone.utc))
    assert market.get_daily_bars.call_args.args[1:3] == (date(2026, 11, 25), date(2026, 11, 27))


@pytest.mark.parametrize("missing", [date(2026, 7, 2), date(2026, 7, 6)])
def test_missing_exact_session_remains_pending_without_substituting_another_day(missing):
    event, version, market = fixture()
    bars = market.get_daily_bars.return_value.data["A.US"]
    market.get_daily_bars.return_value.data["A.US"] = [b for b in bars if b.trade_date != missing] + [
        NS(trade_date=date(2026, 7, 1), open=99, close=100, low=98, high=102),
        NS(trade_date=date(2026, 7, 7), open=99, close=100, low=98, high=102),
    ]
    actual = ContextCollector(None, market).actual(event, version, NOW)
    assert review_prediction(version.prediction, actual, version.context)["status"] == "pending"


@pytest.mark.parametrize("field,value", [("close", float("nan")), ("open", 0), ("high", 90), ("low", -1)])
def test_invalid_daily_bar_cannot_complete_review(field, value):
    event, version, market = fixture()
    setattr(market.get_daily_bars.return_value.data["A.US"][-1], field, value)
    actual = ContextCollector(None, market).actual(event, version, NOW)
    assert actual["ohlc"] is None
    assert review_prediction(version.prediction, actual, version.context)["status"] == "pending"


def test_db_error_is_a_failure_not_an_endless_data_pending():
    event, version, market = fixture()
    market.get_daily_bars.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        ContextCollector(None, market).actual(event, version, NOW)


def test_price_review_never_initializes_llm_or_uses_paid_slots(monkeypatch):
    from finance_analysis.earnings_outlook.service import EarningsOutlookService
    monkeypatch.setattr("finance_analysis.earnings_outlook.service.LLMClient", Mock(side_effect=AssertionError("LLM")))
    repo = Mock()
    repo.pending_reviews.return_value = []
    service = EarningsOutlookService(repo=repo, collector=ContextCollector(repo, fixture()[2]))
    assert service.review() == {"results": []}
    repo.slot.assert_not_called()
