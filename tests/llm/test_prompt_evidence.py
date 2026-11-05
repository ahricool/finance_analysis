"""Synthetic inputs exercise evidence identity, adverse paths and display boundaries."""

from copy import deepcopy
import json

import pytest

from finance_analysis.earnings_outlook.prompt_context import project_input
from finance_analysis.earnings_outlook.prompts import render_input
from finance_analysis.holdings_review.prompt import bar_summary
from finance_analysis.llm.prompting import reference_tables
from finance_analysis.options_intelligence.prompts import explanation_payload
from tests.prompt_tables import tables, read_reference


def test_scalar_lists_and_empty_values_remain_inline_and_round_trip():
    values = ["s1", "a,b", "x|y", 'a"b', "a\nb", "```", "NA", "\\", None, 0, False]
    data = dict(source_ids=values, empty=[], missing=None, zero=0, flag=False, literal="NA", obj={})
    prompt = reference_tables(data, "测试数据")
    assert len(tables(prompt)) == 1
    decoded = read_reference(prompt)
    assert decoded == data
    assert tables(prompt)["data"][0]["source_ids"] == json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def test_facts_deduplicate_exact_identity_only_and_keep_resolvable_references():
    fact = dict(
        text="同一条事实", kind="guidance", quarter="2026-Q3", basis="adjusted", as_of="2026-11-04", source_ids=["s1"]
    )
    different = [
        dict(fact, quarter="2026-Q4"),
        dict(fact, basis="gaap"),
        dict(fact, as_of="2026-11-03"),
        dict(fact, source_ids=["s2"]),
        dict(fact, text="同一季度的相反指引"),
    ]
    frozen = dict(
        context=dict(guidance_evidence=[fact], operating_evidence=[fact, *different]),
        research=dict(
            facts=[fact, *different],
            sources=[dict(source_id="s1"), dict(source_id="s2")],
            conflicts=[dict(source_ids=["s1", "s2"], description="口径冲突")],
        ),
    )
    before = deepcopy(frozen)
    view = project_input(frozen)
    assert frozen == before
    assert len(view["facts"]) == 6
    identities = {f["fact_id"]: f for f in view["facts"]}
    assert view["context"]["guidance_fact_ids"] == view["research"]["fact_ids"][:1]
    assert set(view["context"]["operating_fact_ids"]) <= identities.keys()
    assert set(view["research"]["fact_ids"]) == identities.keys()
    assert view["research"]["conflicts"] == frozen["research"]["conflicts"]
    assert all(set(f["source_ids"]) <= {"s1", "s2"} for f in view["facts"])
    shuffled = deepcopy(frozen)
    shuffled["research"]["facts"].reverse()
    assert {f["fact_id"] for f in project_input(shuffled)["facts"]} == identities.keys()
    assert render_input(frozen).count("同一季度的相反指引") == 1


def test_unresolved_source_is_explicit_without_fabricated_evidence():
    view = project_input(dict(context={}, research=dict(facts=[dict(text="x", source_ids=["missing"])], sources=[])))
    assert view["research"]["sources"] == [dict(source_id="missing", status="unresolved_in_frozen_input")]


def test_stock_event_trigger_terms_and_contract_risks_survive_projection():
    front = dict(expiration="2026-11-13", dte=9, atm_iv=0.65, source="provider", feed_type="delayed", raw_unused="drop")
    back = dict(front, expiration="2026-12-18", dte=44, atm_iv=0.4)
    inversion = dict(
        contract_symbol="",
        event_type="IV_TERM_INVERSION",
        value=0.25,
        reference=dict(front=front, back=back),
        severity=75,
        source="provider",
        feed_type="delayed",
        data_time="2026-11-04T21:00:00Z",
        explanation="期限倒挂",
    )
    illiquid = dict(
        inversion,
        contract_symbol="RISK",
        event_type="WIDE_BID_ASK_SPREAD",
        severity=99,
        value=0.3,
        reference={"allowance": 0.05},
        explanation="点差异常",
    )
    contracts = [
        dict(symbol=f"BUSY{i}", events=["VOLUME"], volume_percentile=99, data_source="provider", feed_type="delayed")
        for i in range(15)
    ]
    risk = dict(
        symbol="RISK",
        events=["WIDE_BID_ASK_SPREAD"],
        volume_percentile=None,
        spread=0.3,
        quote_status="valid",
        data_source="provider",
        feed_type="delayed",
        quote_timestamp="2026-11-04T21:00:00Z",
    )
    conflict = dict(risk, quote_timestamp="2026-11-04T20:00:00Z", spread=0.5)
    original = dict(
        symbol="TEST.US",
        events=[inversion, illiquid, deepcopy(illiquid)],
        term_structure=[front, back],
        contracts=contracts + [risk, risk, conflict, dict(symbol="ORDINARY", events=[])],
    )
    before = deepcopy(original)
    view = explanation_payload(original)
    assert original == before
    assert len(view["events"]) == 2
    term = next(e for e in view["events"] if e["event_type"] == "IV_TERM_INVERSION")
    assert term["reference"]["front"]["expiration"] == "2026-11-13"
    assert term["reference"]["back"]["atm_iv"] == 0.4
    assert term["value"] == 0.25 and term["data_time"] == "2026-11-04T21:00:00Z"
    assert "raw_unused" not in term["reference"]["front"]
    risks = [c for c in view["anomalous_contracts"] if c["symbol"] == "RISK"]
    assert len(risks) == 2  # Exact duplicates removed; conflicting observations preserved.
    assert any(r.get("spread") == 0.5 for r in risks)
    assert view["anomalous_contracts"][0]["symbol"] == "RISK"
    assert risks[0]["event_ids"] and "ORDINARY" not in str(view)
    assert all(e["source_id"] in {s["source_id"] for s in view["sources"]} for e in view["events"])


def rows(closes, volumes):
    return [[f"2026-11-{i+1:02}", 10, 15, 5, c, v] for i, (c, v) in enumerate(zip(closes, volumes))]


def test_summary_distinguishes_recent_weakness_from_rebound_with_same_old_summary():
    weak = bar_summary(rows([10, 11, 14, 13, 12.5, 12], [100, 100, 100, 200, 200, 200]))
    rebound = bar_summary(rows([10, 11, 8, 9, 10, 12], [100, 100, 100, 50, 50, 50]))
    for field in ("first_close", "last_close", "window_high", "window_low", "close_change_pct"):
        assert weak[field] == rebound[field]
    assert weak["last_bar_change_pct"] < 0 < rebound["last_bar_change_pct"]
    assert weak["recent_3_change_pct"] < 0 < rebound["recent_3_change_pct"]
    assert weak["ma5_deviation_pct"] < 0 < rebound["ma5_deviation_pct"]
    assert weak["volume_last3_vs_prior3"] == 2 and rebound["volume_last3_vs_prior3"] == 0.5
    assert weak["from_window_high_pct"] == pytest.approx(-20)


def test_summary_does_not_invent_missing_or_zero_denominator_features():
    partial = bar_summary(rows([10, None, 12], [0, None, 0]))
    assert partial["last_bar_change_pct"] is None and partial["recent_3_change_pct"] is None
    assert partial["ma5_deviation_pct"] is None and partial["volume_last3_vs_prior3"] is None
    zeros = bar_summary(rows([10] * 6, [0] * 6))
    assert zeros["volume_last3_vs_prior3"] is None
    assert zeros["last_bar_change_pct"] == 0
