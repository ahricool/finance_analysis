"""Structured advice must remain inside the frozen user's actual portfolio."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from finance_analysis.holdings_review.decision import ReviewDecisionMaker, validate_decision, sources
from finance_analysis.llm import LLMResult


def context():
    return {
        "market": "CN",
        "holdings": [{"position_id": "11", "symbol": "600519.SH", "data_complete": True}],
        "portfolio": {"cash": 10000, "valuation_complete": True},
    }


def output(action="BUY"):
    return {
        "market_state": "NEUTRAL",
        "conclusion": "市场宽度尚待确认",
        "confidence": "MEDIUM",
        "sectors": [],
        "risks": [],
        "positions": [
            {
                "position_id": "11",
                "symbol": "600519.SH",
                "action": action,
                "change_pct": 10,
                "rationale": "趋势与当前价格仍处于观察区间",
                "condition": "突破后确认，且现金允许",
                "invalidation": "跌回观察区间",
                "confidence": "MEDIUM",
            }
        ],
        "watchpoints": ["关注尾盘成交"],
    }


@pytest.mark.parametrize("change", [dict(position_id="22"), dict(symbol="AAPL.US")])
def test_cannot_recommend_new_or_other_users_positions(change):
    raw = output()
    raw["positions"][0].update(change)
    with pytest.raises(ValueError):
        validate_decision(raw, context())


def test_duplicate_missing_and_incomplete_holdings():
    raw = output()
    raw["positions"].append(deepcopy(raw["positions"][0]))
    with pytest.raises(ValueError):
        validate_decision(raw, context())
    raw["positions"] = []
    assert validate_decision(raw, context())["positions"][0]["action"] == "WATCH"
    snapshot = context()
    snapshot["holdings"][0]["data_complete"] = False
    row = validate_decision(output(), snapshot)["positions"][0]
    assert row["action"] == "WATCH" and row["change_pct"] == 0


def test_percentage_and_add_condition_constraints():
    raw = output()
    raw["positions"][0]["change_pct"] = float("nan")
    with pytest.raises(ValueError):
        validate_decision(raw, context())
    raw = output()
    raw["positions"][0]["condition"] = ""
    with pytest.raises(ValueError):
        validate_decision(raw, context())
    assert validate_decision(output("SELL"), context())["positions"][0]["change_pct"] == 100
    assert validate_decision(output("HOLD"), context())["positions"][0]["change_pct"] == 0


def test_one_web_search_request_with_uid_and_honest_transport_evidence():
    import json

    calls = []

    class Client:
        def is_available(self):
            return True

        def complete_text(self, request, validator):
            calls.append(request)
            text = json.dumps(output())
            validator(text)
            return LLMResult(text=text, backend="api", search_evidence={"status": "unverified"})

    decision, evidence, _ = ReviewDecisionMaker(Client()).decide(7, context())
    assert not decision["degraded"]
    assert len(calls) == 1 and calls[0].web_search and calls[0].uid == 7
    assert evidence["status"] == "unverified"
    assert sources(
        {
            "status": "confirmed",
            "citations": [
                {"url": "javascript:alert(1)", "title": "bad"},
                {"url": "https://example.com", "title": "公告"},
            ],
        }
    ) == [{"url": "https://example.com", "title": "公告"}]


def test_unavailable_llm_produces_explicit_watch_only_fallback():
    maker = ReviewDecisionMaker(SimpleNamespace(is_available=lambda: False))
    decision, proof, _ = maker.decide(1, context())
    assert decision["degraded"] and decision["positions"][0]["action"] == "WATCH"
    assert proof["status"] == "unavailable"


def test_combined_additions_cannot_exceed_cash():
    snapshot = context()
    snapshot["holdings"][0]["market_value"] = 10000
    snapshot["portfolio"]["cash"] = 100
    with pytest.raises(ValueError, match="cash"):
        validate_decision(output(), snapshot)


def test_cn_t_plus_one_caps_or_suppresses_sell_advice():
    snapshot = context()
    snapshot["holdings"][0].update(quantity=100, today_buy_quantity=40)
    row = validate_decision(output("SELL"), snapshot)["positions"][0]
    assert row["action"] == "REDUCE" and row["change_pct"] == 60
    snapshot["holdings"][0]["today_buy_quantity"] = 100
    assert validate_decision(output("SELL"), snapshot)["positions"][0]["action"] == "WATCH"
