"""Retrospective actual enrichment uses fake search/provider evidence only."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock
import json

import pytest

from finance_analysis.earnings_outlook.context import ContextCollector
from finance_analysis.earnings_outlook.rules import normalize_prediction, review_prediction
from finance_analysis.llm.types import LLMResult
from .test_rules import context, raw

NOW = datetime(2026, 7, 6, 22, tzinfo=timezone.utc)


def fixture():
    c = context()
    event = NS(
        symbol="A.US", event_date=date(2026, 7, 2), reporting_period=None,
        reported_eps=None, currency=None, raw_payload_json={},
    )
    version = NS(id=42, context=c, prediction=normalize_prediction(raw(), c), target_trading_date=date(2026, 7, 6))
    market = Mock()
    market.get_calendar_sources.return_value = {}
    market.get_daily_bars.return_value = NS(data={
        "A.US": [NS(trade_date=date(2026, 7, 6), open=100, close=98, low=95, high=102)]
    })
    bundle = {
        "sources": [dict(
            source_id="ir", title="A Q2 reported earnings", url="https://example.com/ir/q2",
            published_at="2026-07-02T21:00:00Z", source_type="official", symbol="A.US", quarter="2026-Q2",
        )],
        "actual": {
            k: {**c["consensus"][k], "value": value, "unit": unit, "symbol": "A.US", "source_ids": ["ir"]}
            for k, value, unit in (("eps", -0.9, "per_share"), ("revenue", 102_000_000, "currency_units"))
        },
    }
    llm = Mock()

    def complete(request, validator):
        text = json.dumps(bundle)
        validator(text)
        return LLMResult(text=text, backend="fake", model="fake", search_evidence={"status": "confirmed"})

    llm.complete_text.side_effect = complete
    return event, version, market, llm, bundle


def test_official_actuals_resolve_missing_provider_metadata_without_changing_prediction():
    event, version, market, llm, bundle = fixture()
    event.raw_payload_json = {"longbridge": {"raw": {"details": [
        {"value_type": "actual_revenue", "value_raw": "102000000"},
        {"value_type": "actual_eps", "value_raw": "-0.9"},
    ]}}}
    before = deepcopy(version.prediction)
    result = ContextCollector(None, market, llm).actual(event, version, NOW)
    assert result["eps"]["basis"] == "adjusted"
    assert result["revenue"]["value"] == 102 and result["revenue"]["unit"] == "USD_million"
    assert review_prediction(version.prediction, result, version.context)["status"] == "completed"
    assert event.reporting_period is None and version.prediction == before
    request = llm.complete_text.call_args.args[0]
    assert request.web_search and request.prefer_search and request.call_type == "earnings_actuals"
    assert json.loads(request.prompt)["reporting_period"] == "2026-Q2"


@pytest.mark.parametrize("invalid", ["unverified", "undated", "wrong_quarter", "wrong_symbol"])
def test_search_claims_need_transport_and_matching_dated_official_sources(invalid):
    event, version, market, llm, bundle = fixture()
    if invalid == "unverified":
        llm.complete_text.side_effect = None
        llm.complete_text.return_value = LLMResult(
            text=json.dumps(bundle), backend="fake", search_evidence={"status": "unverified"}
        )
    else:
        field, value = {
            "undated": ("published_at", None), "wrong_quarter": ("quarter", "2026-Q1"),
            "wrong_symbol": ("symbol", "B.US"),
        }[invalid]
        bundle["sources"][0][field] = value
    result = ContextCollector(None, market, llm).actual(event, version, NOW)
    review = review_prediction(version.prediction, result, version.context)
    assert review["eps"] == review["revenue"] == "unknown"


def test_official_gaap_eps_is_never_relabeled_to_adjusted_consensus():
    event, version, market, llm, bundle = fixture()
    event.raw_payload_json = {"longbridge": {"raw": {"details": [
        {"value_type": "actual_eps", "value_raw": "-0.9"},
    ]}}}
    bundle["actual"]["eps"].update(basis="gaap", value=-1.2)
    result = ContextCollector(None, market, llm).actual(event, version, NOW)
    assert result["eps"]["basis"] == "gaap"
    assert result["eps"]["value"] == -1.2 and result["eps"]["source"] == "official"
    assert review_prediction(version.prediction, result, version.context)["eps"] == "unknown"


def test_cached_actual_keeps_its_sources_when_a_later_search_reuses_source_ids():
    event, version, market, llm, bundle = fixture()
    revenue = bundle["actual"].pop("revenue")
    bundle["sources"][0]["url"] = "https://example.com/ir/eps"
    collector = ContextCollector(None, market, llm)
    first = collector.actual(event, version, NOW)
    assert first["eps"]["sources"][0]["url"] == "https://example.com/ir/eps"
    previous = dict(prediction_id=version.id, actual=first)
    bundle["actual"] = {"revenue": revenue}
    bundle["sources"][0]["url"] = "https://example.com/ir/revenue"
    second = collector.actual(event, version, NOW + timedelta(days=1), previous=previous)
    assert second["eps"]["sources"][0]["url"] == "https://example.com/ir/eps"
    assert second["revenue"]["sources"][0]["url"] == "https://example.com/ir/revenue"
    assert review_prediction(version.prediction, second, version.context)["status"] == "completed"


def test_calendar_rows_use_snapshot_quarter_and_cannot_borrow_it_when_missing():
    event, version, market, llm, bundle = fixture()
    source = Mock()
    market.get_calendar_sources.return_value = {"test": source}
    source.fetch_earnings_calendar.return_value = NS(events=[
        dict(symbol="B.US", reporting_period="2026-Q2", event_date="2026-07-02", reported_eps=999),
        dict(symbol="A.US", reporting_period="2026-Q1", event_date="2026-07-02", reported_eps=999),
        dict(symbol="A.US", reporting_period="2026-Q2", event_date="2026-07-01", reported_eps=999),
        dict(symbol="A.US", reporting_period=None, event_date="2026-07-02", reported_eps=-0.9, currency="USD"),
    ])
    result = ContextCollector(None, market).actual(event, version, NOW)
    assert result["eps"]["value"] == -0.9
    assert result["eps"]["quarter"] is None and result["eps"]["basis"] is None
    assert review_prediction(version.prediction, result, version.context)["eps"] == "unknown"


def test_review_cache_preserves_comparable_values_and_limits_failed_searches():
    event, version, market, llm, bundle = fixture()
    collector = ContextCollector(None, market, llm)
    first = collector.actual(event, version, NOW)
    previous = dict(prediction_id=version.id, actual=first)
    event.reported_eps = 99  # An incomplete provider value cannot displace verified actuals.
    second = collector.actual(event, version, NOW + timedelta(days=1), previous=previous)
    assert second["eps"] == first["eps"] and llm.complete_text.call_count == 1

    llm.complete_text.side_effect = RuntimeError("temporary search failure")
    market.get_daily_bars.side_effect = RuntimeError("temporary DB failure")
    failed = collector.actual(event, version, NOW)
    assert failed["research"]["status"] == "failed" and failed["ohlc"] is None
    previous = dict(prediction_id=version.id, actual=failed)
    collector.actual(event, version, NOW + timedelta(minutes=5), previous=previous)
    assert llm.complete_text.call_count == 2  # Failure is persisted for this NY date too.
    collector.actual(event, version, NOW + timedelta(days=1), previous=previous)
    assert llm.complete_text.call_count == 3


def test_stale_or_uncomparable_predictions_do_not_trigger_paid_search():
    event, version, market, llm, bundle = fixture()
    collector = ContextCollector(None, market, llm)
    stale = collector.actual(event, version, NOW + timedelta(days=4))
    assert "7" in stale["research"]["reason"]
    for metric in ("eps", "revenue"):
        version.prediction[metric]["consensus"] = None
    collector.actual(event, version, NOW)
    llm.complete_text.assert_not_called()
