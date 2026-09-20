"""LLM review only CONFIRM/REJECT; action/target from the model are ignored."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from [REDACTED].trade_engine.models import ReviewDecision, TradeSignalCandidate  # pragma: allowlist secret
from [REDACTED].trade_engine.reviewer import TradeSignalReviewer  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def _candidate(*, action="REDUCE", target="500", severity="soft"):
    return TradeSignalCandidate(
        market="US",
        account_id="1",
        position_id="11",
        symbol="AAPL.US",
        strategy_key="exit_v1",
        strategy_version="1",
        action=action,
        suggested_target_quantity=None if target is None else Decimal(target),
        severity=severity,
        reason="x",
        evidence={"hard": severity == "hard"},
        evaluated_at=NOW,
        signal_key="k",
    )


class FakeClient:
    def __init__(self, payload: str):
        self.payload = payload
        self.requests = []

    def complete_text(self, request, validator=None):
        self.requests.append(request)
        if validator is not None:
            validator(self.payload)
        return SimpleNamespace(text=self.payload)


def test_reviewer_ignores_llm_action_and_target_and_enables_web_search():
    payload = (
        '{"results":[{"id":"k","decision":"CONFIRM","reason":"ok",'
        '"comment":"建议全部退出","action":"EXIT","target":"0"}]}'
    )
    client = FakeClient(payload)
    decisions = TradeSignalReviewer(client=client).review([_candidate()])
    assert client.requests[0].web_search is True
    assert "AAPL.US" in client.requests[0].prompt
    decision = decisions["k"]
    assert decision.decision == "CONFIRM"
    assert decision.reason == "ok"
    assert decision.comment == "建议全部退出"


def test_reviewer_parses_reject_comment():
    payload = '{"results":[{"id":"k","decision":"REJECT","reason":"停牌","comment":"等待复牌"}]}'
    decisions = TradeSignalReviewer(client=FakeClient(payload)).review([_candidate()])
    assert decisions["k"].decision == "REJECT"
    assert decisions["k"].reason == "停牌"
    assert decisions["k"].comment == "等待复牌"


def test_missing_llm_result_is_reject():
    payload = '{"results":[]}'
    decisions = TradeSignalReviewer(client=FakeClient(payload)).review([_candidate()])
    assert decisions["k"].decision == "REJECT"
    assert decisions["k"].failed is True
