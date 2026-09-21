"""Market-level LLM validation: target quantity, ADD guardrail, reduce from risk."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.trade_engine.models import (  # pragma: allowlist secret
    MarketTradeDecisionContext,
    PortfolioRiskFacts,
    PreviousLLMState,
    StrategySignal,
    SymbolRiskFacts,
)
from finance_analysis.trade_engine.resolver import MarketDecisionResolver, validate_market_decision  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def _signal(*, action="ADD", quantity="200", target="1200", symbol="AAPL.US"):
    return StrategySignal(
        strategy_key="add_v1" if action == "ADD" else "exit_v1",
        strategy_version="1",
        market="US",
        account_id="1",
        position_id="11",
        symbol=symbol,
        action=action,
        suggested_quantity=None if quantity is None else Decimal(quantity),
        suggested_target_quantity=None if target is None else Decimal(target),
        reason="x",
        evidence={"current_quantity": "1000"},
        evaluated_at=NOW,
    )


def _context(*, signals=(), enabled=True, quantity="1000", extra_positions=()):
    positions = [
        {
            "symbol": "AAPL.US",
            "position_id": "11",
            "quantity": quantity,
            "trade_engine_enabled": enabled,
        },
        *extra_positions,
    ]
    return MarketTradeDecisionContext(
        market="US",
        cash=Decimal("350000"),
        nav=Decimal("1000000"),
        gross_exposure=Decimal("0.65"),
        policy={"max_gross_exposure": "0.50"},
        positions=tuple(positions),
        strategy_signals=tuple(signals),
        portfolio_risk=PortfolioRiskFacts(
            market="US",
            nav=Decimal("1000000"),
            cash=Decimal("350000"),
            gross_exposure=Decimal("0.65"),
            max_gross_exposure=Decimal("0.50"),
            total_open_risk=Decimal("0.018"),
            total_open_risk_limit=Decimal("0.02"),
            valuation_complete=True,
            positions={
                "AAPL.US": SymbolRiskFacts(Decimal("0.18"), Decimal("0.10"), Decimal("0.008"), Decimal("0.005")),
            },
        ),
        previous=PreviousLLMState(summary="A"),
        web_search_available=True,
        evaluated_at=NOW,
    )


class FakeClient:
    def __init__(self, payload: str, backend="api"):
        self.payload = payload
        self.requests = []
        self.config = SimpleNamespace(backend=backend)

    def is_available(self):
        return True

    def complete_text(self, request, validator=None):
        self.requests.append(request)
        if validator is not None:
            validator(self.payload)
        return SimpleNamespace(text=self.payload)


def test_resolver_enables_web_search_for_api_backend():
    payload = '{"market":"US","portfolio_reason":"减仓","positions":[{"symbol":"AAPL.US","current_quantity":"1000","target_quantity":"700","reason":"风险"}],"state_summary":"B"}'
    client = FakeClient(payload)
    context = _context(signals=[_signal(action="REDUCE", quantity="300", target="700")])
    decision = MarketDecisionResolver(client=client).decide(context)
    assert client.requests[0].web_search is True
    assert "0.65" in client.requests[0].prompt
    assert "0.50" in client.requests[0].prompt
    assert context.previous.summary == "A"
    assert "previous_llm_state" in client.requests[0].prompt
    assert decision.positions[0].action == "REDUCE"
    assert decision.positions[0].target_quantity == Decimal("700")
    assert decision.state_summary == "B"


def test_cli_backend_does_not_claim_web_search():
    payload = '{"market":"US","portfolio_reason":"保持","positions":[],"state_summary":"keep"}'
    client = FakeClient(payload, backend="cli")
    context = _context(signals=())
    context = MarketTradeDecisionContext(
        market=context.market,
        cash=context.cash,
        nav=context.nav,
        gross_exposure=context.gross_exposure,
        policy=context.policy,
        positions=context.positions,
        strategy_signals=context.strategy_signals,
        portfolio_risk=context.portfolio_risk,
        previous=context.previous,
        web_search_available=False,
        evaluated_at=context.evaluated_at,
    )
    MarketDecisionResolver(client=client).decide(context)
    assert client.requests[0].web_search is False
    assert "web_search_available" in client.requests[0].prompt


def test_add_without_strategy_is_clamped_to_current():
    decision = validate_market_decision(
        _context(signals=()),
        {"positions": [{"symbol": "AAPL.US", "target_quantity": "1200", "reason": "想加"}]},
    )
    assert decision.positions[0].target_quantity == Decimal("1000")
    assert decision.positions[0].action == "NO_ACTION"


def test_add_cannot_exceed_strategy_quantity():
    decision = validate_market_decision(
        _context(signals=[_signal(action="ADD", quantity="200", target="1200")]),
        {"positions": [{"symbol": "AAPL.US", "target_quantity": "1500", "reason": "追"}]},
    )
    assert decision.positions[0].action == "ADD"
    assert decision.positions[0].target_quantity == Decimal("1200")


def test_reduce_without_exit_signal_is_allowed():
    decision = validate_market_decision(
        _context(signals=()),
        {"positions": [{"symbol": "AAPL.US", "target_quantity": "700", "reason": "仓位超限"}]},
    )
    assert decision.positions[0].action == "REDUCE"
    assert decision.positions[0].target_quantity == Decimal("700")


def test_disabled_position_target_forced_to_current():
    decision = validate_market_decision(
        _context(signals=[_signal(action="REDUCE", target="0")], enabled=False),
        {"positions": [{"symbol": "AAPL.US", "target_quantity": "0", "reason": "想清"}]},
    )
    assert decision.positions[0].target_quantity == Decimal("1000")
    assert decision.positions[0].action == "NO_ACTION"


def test_prompt_contains_portfolio_and_repeat_advice_guidance():
    from finance_analysis.trade_engine.resolver import _SYSTEM, serialize_context

    for text in ("previous_llm_state", "last_decision", "recent_trade_signals", "NO_ACTION",
                 "避免机械重复", "风险明显恶化", "所有加仓合计现金", "max_symbol_weight",
                 "total open risk/total risk limit", "最终执行决定由用户负责"):
        assert text in _SYSTEM
    payload = serialize_context(_context(signals=[_signal()]))
    assert payload["cash"] == "350000"
    assert payload["nav"] == "1000000"
    assert payload["strategy_signals"]
    risk = payload["portfolio_risk"]
    assert risk["gross_exposure"] == "0.65"
    assert risk["max_gross_exposure"] == "0.50"
    assert risk["total_open_risk"] == "0.018"
    assert risk["total_open_risk_limit"] == "0.02"
    assert risk["positions"]["AAPL.US"] == {
        "weight": "0.18", "max_weight": "0.10", "open_risk": "0.008", "risk_limit": "0.005",
    }
