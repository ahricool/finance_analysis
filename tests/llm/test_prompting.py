"""Presentation must not invent facts or break table ownership and domain limits."""

from copy import deepcopy

import json

from finance_analysis.llm.prompting import cell, reference_tables
from finance_analysis.holdings_review.prompt import render_input as holdings_input
from finance_analysis.options_intelligence.prompts import explanation_payload
from tests.prompt_tables import tables


def test_nested_tables_link_children_and_quote_untrusted_multiline_text():
    data = {
        "candidates": [
            {"symbol": "AAA.US", "name": 'test,"name"\n```\n# instruction', "events": [{"type": "a"}]},
            {"symbol": "BBB.US", "events": [{"type": "b"}]},
        ]
    }
    before = deepcopy(data)
    result = tables(reference_tables(data, "候选与事件按父行关联"))
    assert data == before
    parents = result["data/candidates"]
    children = result["data/candidates/events"]
    assert parents[0]["name"] == data["candidates"][0]["name"]
    assert [c["parent_ref"] for c in children] == [p["ref"] for p in parents]
    assert [c["type"] for c in children] == ["a", "b"]


def test_numeric_precision_preserves_small_values_and_missingness():
    assert cell(12.345678) == "12.35"
    assert cell(0.000012345678) == "1.235e-05"
    assert cell(0) == "0" and cell(False) == "false"
    assert cell(None) == cell(float("nan")) == cell(float("inf")) == "NA"


def test_holdings_projection_keeps_every_position_and_summarizes_bars_without_mutation():
    context = dict(
        market="CN",
        holdings=[
            dict(
                position_id="p1",
                symbol="AAA.SH",
                daily_bars=[["2026-11-01", 10, 12, 9, 11, 100], ["2026-11-02", 11, 14, 10, 13, 200]],
                minute_bars=[],
                quantity=100,
            ),
            dict(position_id="p2", symbol="BBB.SH", quantity=50),
        ],
        indices=[],
    )
    before = deepcopy(context)
    prompt = holdings_input(context)
    rows = tables(prompt)["data/holdings"]
    assert [r["position_id"] for r in rows] == ["p1", "p2"]
    assert rows[0]["daily_summary.window_high"] == "14"
    assert rows[0]["daily_summary.last_close"] == "13"
    assert "daily_bars" not in prompt
    assert context == before


def test_option_explanation_does_not_send_raw_chain_or_unrelated_payload():
    snapshot = dict(
        symbol="AAA.US",
        computed_at="2026-11-05",
        private_raw="x" * 1000000,
        contracts=[
            dict(
                symbol="contract",
                events=["VOLUME"],
                volume_percentile=90,
                raw_debug="x" * 1000000,
                oi_date="2026-11-04",
            )
        ],
    )
    result = explanation_payload(snapshot)
    assert result["anomalous_contracts"][0]["oi_date"] == "2026-11-04"
    assert "private_raw" not in result and "raw_debug" not in result["anomalous_contracts"][0]


def test_large_holdings_reaches_model_without_dropping_positions():
    from unittest.mock import Mock
    from finance_analysis.holdings_review.decision import ReviewDecisionMaker
    from finance_analysis.llm import LLMResult
    from tests.holdings_review.test_decision import context, output

    client = Mock()
    client.complete_text.return_value = LLMResult(text=json.dumps(output("HOLD")), backend="api")
    snapshot = context()
    snapshot["data_quality"] = ["合成观察资料" * 10000]
    decision, _, _ = ReviewDecisionMaker(client).decide(1, snapshot)
    assert len(client.complete_text.call_args.args[0].prompt) > 40000
    assert not decision["degraded"] and len(decision["positions"]) == 1
