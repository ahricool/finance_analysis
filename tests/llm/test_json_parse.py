# -*- coding: utf-8 -*-
"""Shared LLM JSON parse helpers used by pre-close, news, and Trade Engine review."""

from finance_analysis.llm.json_parse import parse_llm_batch_results, parse_llm_json_response  # pragma: allowlist secret


def test_parse_llm_json_repairs_fenced_and_trailing_comma():
    parsed = parse_llm_json_response(
        """```json
        {"final_decision": "accept", "need_notification": true, "confidence": 0.7,}
        ```"""
    )
    assert parsed is not None
    assert parsed["final_decision"] == "accept"


def test_parse_llm_batch_results_reads_results_array():
    rows = parse_llm_batch_results(
        '{"results": [{"id": "a", "decision": "CONFIRM"}, {"id": "b", "decision": "REJECT"}]}'
    )
    assert [item["id"] for item in rows] == ["a", "b"]
