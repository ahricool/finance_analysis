"""LLM resolver clamps final action to the current Strategy Proposals."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.trade_engine.models import StrategyProposal  # pragma: allowlist secret
from finance_analysis.trade_engine.resolver import TradeDecisionResolver, clamp_decision  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def _proposal(*, action="REDUCE", quantity=None, target="700", key="exit_v1"):
    return StrategyProposal(
        market="US",
        account_id="1",
        position_id="11",
        symbol="AAPL.US",
        strategy_key=key,
        strategy_version="1",
        action=action,
        suggested_quantity=None if quantity is None else Decimal(quantity),
        suggested_target_quantity=None if target is None else Decimal(target),
        reason="x",
        evidence={"current_quantity": "1000"},
        evaluated_at=NOW,
        proposal_key=f"{key}:{action}",
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


def test_resolver_enables_web_search_and_returns_json_action():
    payload = '{"action":"REDUCE","target_quantity":"700","quantity":null,"reason":"保护","strategy_assessments":[]}'
    client = FakeClient(payload)
    decision = TradeDecisionResolver(client=client).resolve(
        [_proposal(), _proposal(action="ADD", quantity="200", target="1200", key="add_v1")]
    )
    assert client.requests[0].web_search is True
    assert "AAPL.US" in client.requests[0].prompt
    assert decision.action == "REDUCE"
    assert decision.target_quantity == Decimal("700")


def test_unknown_action_becomes_no_action():
    decision = clamp_decision(
        [_proposal(action="REDUCE", target="700")],
        {"action": "BUY", "reason": "想买"},
    )
    assert decision.action == "NO_ACTION"


def test_add_quantity_cannot_exceed_proposal():
    decision = clamp_decision(
        [_proposal(action="ADD", quantity="200", target="1200", key="add_v1")],
        {"action": "ADD", "quantity": "500", "reason": "追"},
    )
    assert decision.action == "ADD"
    assert decision.quantity == Decimal("200")


def test_reduce_cannot_be_more_aggressive_than_proposal():
    decision = clamp_decision(
        [_proposal(action="REDUCE", target="700")],
        {"action": "REDUCE", "target_quantity": "100", "reason": "清仓"},
    )
    assert decision.target_quantity == Decimal("700")
