"""Business boundaries without network/model calls."""

from datetime import date, datetime, timezone
from types import SimpleNamespace as NS
import pytest

from finance_analysis.earnings_outlook.rules import (
    compare,
    event_window,
    clean_research,
    normalize_prediction,
    review_prediction,
    released,
)
from finance_analysis.earnings_outlook.universe import resolve_members

NOW = datetime(2026, 7, 1, 15, tzinfo=timezone.utc)


def event(day=date(2026, 7, 2), session="amc", **kw):
    return NS(event_date=day, market_session=session, event_datetime=None, reported_eps=None, **kw)


def test_union_deduplicates_instrument_identity_and_excludes_inactive_etfs():
    a = NS(id=1, code="A.US", name="A", market="US", instrument_type="STOCK", listing_status="ACTIVE")
    b = NS(id=2, code="B.US", name="B", market="US", instrument_type="STOCK", listing_status="ACTIVE")
    etf = NS(id=3, code="ETF.US", name="ETF", market="US", instrument_type="ETF", listing_status="ACTIVE")
    dead = NS(**{**vars(a), "id": 4, "listing_status": "DELISTED"})
    calls = []

    def resolve(key):
        calls.append(key)
        return [a, etf, dead] if key == "us_sp500" else [a, b]

    members = resolve_members(NS(resolve_universe=resolve))
    assert set(members) == {"A.US", "B.US"}
    assert members["A.US"]["memberships"] == ["us_sp500", "us_nasdaq100"]
    assert calls == ["us_sp500", "us_nasdaq100"]
    with pytest.raises(ValueError, match="Empty"):
        resolve_members(NS(resolve_universe=lambda _: []))


@pytest.mark.parametrize(
    "metric,estimate,value,expected",
    [
        ("eps", -1, -0.97, "beat"),
        ("eps", -1, -1.03, "miss"),
        ("eps", -1, -1.02, "meet"),
        ("eps", 0, 0.01, "meet"),
        ("eps", 0.1, 0.105, "meet"),
        ("eps", 0.1, 0.12, "beat"),
        ("revenue", 100, 101, "meet"),
        ("revenue", 100, 98, "miss"),
        ("eps", None, 1, "unknown"),
    ],
)
def test_meet_tolerances(metric, estimate, value, expected):
    assert compare(value, estimate, metric) == expected


def test_first_session_holiday_weekend_early_close_and_unknown():
    amc = event_window(event())  # July 3 observed Independence Day, then weekend.
    assert amc["target_trading_date"] == date(2026, 7, 6)
    assert amc["cutoff"].hour == 20
    bmo = event_window(event(session="bmo"))
    assert bmo["target_trading_date"] == date(2026, 7, 2)
    assert bmo["cutoff"].hour == 4  # conservative NY midnight
    unknown = event_window(event(session="unknown"))
    assert unknown["provisional"] and unknown["assumption"]
    assert unknown["target_trading_date"] == date(2026, 7, 6)
    early = event_window(event(date(2026, 11, 27)))
    assert early["cutoff"].hour == 18  # NY 13:00 early close
    assert released(event(), amc["cutoff"], amc)
    e = event()
    e.reported_eps = 0
    assert released(e, NOW, amc)


def context():
    return dict(
        event={"reporting_period": "2026-Q2"},
        consensus={
            key: dict(
                value=value,
                quarter="2026-Q2",
                currency="USD",
                unit=unit,
                basis="adjusted" if key == "eps" else None,
                source="official consensus",
                as_of=NOW.isoformat(),
            )
            for key, value, unit in (("eps", -1, "per_share"), ("revenue", 100, "USD_million"))
        },
        reference_price=100,
        reference_price_at=NOW.isoformat(),
        reference_price_session="regular",
        provisional=False,
        target_trading_date="2026-07-06",
        assumption=None,
        guidance_evidence=["given"],
    )


def raw():
    return dict(
        eps={"expected_value": -0.9},
        revenue={"expected_value": 102},
        guidance="above",
        earnings_confidence=9,
        reaction_confidence=8,
        expected_close=98,
        intraday_low=94,
        intraday_high=103,
    )


def test_beat_can_have_negative_price_response_and_sections_degrade_independently():
    c = context()
    p = normalize_prediction(raw(), c)
    assert p["eps"]["judgment"] == "beat" and p["response_direction"] == "down"
    assert p["expected_return_pct"] == pytest.approx(-2)
    c["consensus"]["eps"]["basis"] = None
    p = normalize_prediction(raw(), c)
    assert p["eps"]["judgment"] == "unknown" and p["earnings_confidence"] <= 6
    c["reference_price"] = None
    p = normalize_prediction(raw(), c)
    assert p["revenue"]["judgment"] == "beat" and p["expected_close"] is None
    c = context()
    c["provisional"] = True
    assert normalize_prediction(raw(), c)["reaction_confidence"] <= 6
    assert normalize_prediction({**raw(), "intraday_low": 200}, context())["expected_close"] is None


def test_no_future_sources_and_conflicts_preserve_individual_sources():
    bundle = {
        "sources": [
            dict(source_id=sid, url="https://example.com/" + sid, published_at=dt)
            for sid, dt in (("past", "2026-07-01T10:00:00Z"), ("future", "2026-07-01T16:00:00Z"), ("unknown", None))
        ],
        "facts": [dict(text="future leaked fact", source_ids=["future"]), dict(text="past", source_ids=["past"])],
        "conflicts": [{"source_ids": ["past", "unknown"], "reason": "different quarter"}],
    }
    clean = clean_research(bundle, NOW, NOW)
    assert clean["excluded_source_ids"] == ["future"]
    assert [f["text"] for f in clean["facts"]] == ["past"]
    assert clean["publication_unknown"] and clean["conflicts"] == bundle["conflicts"]


def test_actual_comparison_requires_same_quarter_basis_and_unit():
    c = context()
    p = normalize_prediction(raw(), c)
    actual = {k: {**c["consensus"][k], "value": p[k]["expected_value"]} for k in ("eps", "revenue")}
    actual["ohlc"] = dict(open=100, high=102, low=95, close=99)
    review = review_prediction(p, actual, c)
    assert review["eps"] == "beat" and review["status"] == "completed"
    assert review["range_covered"] and review["close_error"] == -1
    actual["eps"]["basis"] = "gaap"
    assert review_prediction(p, actual, c)["eps"] == "unknown"
    actual["revenue"]["quarter"] = "2026-Q1"
    assert review_prediction(p, actual, c)["revenue"] == "unknown"


def test_future_consensus_cannot_leak_through_research_into_analysis():
    bundle = {
        "sources": [{"source_id": "after", "url": "https://example.com", "published_at": "2026-07-02T10:00:00Z"}],
        "consensus": {"eps": {"value": 999, "source_ids": ["after"], "as_of": "2026-07-02T10:00:00Z"}},
        "conflicts": [{"source_ids": ["after"], "description": "future result"}],
        "uncertainties": ["Actual EPS already reported after cutoff"],
    }
    cleaned = clean_research(bundle, NOW, NOW)
    assert cleaned["consensus"] == {} and cleaned["conflicts"] == [] and cleaned["sources"] == []
    assert cleaned["uncertainties"] == []


def test_persisted_longbridge_revenue_preserves_unknown_basis_and_freezes():
    from finance_analysis.earnings_outlook.context import consensus
    from finance_analysis.earnings_outlook.facts import raw_facts

    e = event(
        raw_payload_json={
            "longbridge": {
                "normalized": {"currency": "USD"},
                "observed_at": NOW.isoformat(),
                "raw": {
                    "details": [
                        {"value_type": "estimate_revenue", "value_raw": "483296990.000000"},
                        {"value_type": "actual_revenue", "value_raw": "508437000.000000"},
                        {"value_type": "actual_eps", "value_raw": "TBA"},
                    ]
                },
            }
        },
        eps_estimate=None,
    )
    revenue = consensus(e)["revenue"]
    assert revenue["value"] == 483296990
    assert revenue["quarter"] is None and revenue["as_of"] is None
    assert raw_facts(e)["actual"]["revenue"]["value"] == 508437000
    assert released(e, NOW, event_window(e))


def test_high_quality_structured_evidence_is_not_capped_for_absent_search():
    r = {
        **raw(),
        "earnings_reason": "给定指引支持",
        "earnings_confidence_reason": "同口径结构化证据充分",
        "reaction_reason": "估值与市场环境",
        "reaction_confidence_reason": "参考价新鲜",
    }
    p = normalize_prediction(r, context())
    assert p["earnings_confidence"] == 9 and p["reaction_confidence"] == 8
    p = normalize_prediction({**r, "eps": "bad section", "scenarios": None}, context())
    assert p["eps"]["judgment"] == "unknown" and p["revenue"]["judgment"] == "beat"
    assert p["expected_close"] == 98
