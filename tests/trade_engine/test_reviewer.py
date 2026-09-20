"""LLM review clamp: no added exposure, hard stop cannot be rejected."""

from datetime import datetime, timezone
from decimal import Decimal

from finance_analysis.trade_engine.models import ReviewDecision, TradeSignalCandidate  # pragma: allowlist secret
from finance_analysis.trade_engine.reviewer import clamp_review  # pragma: allowlist secret

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


def test_llm_cannot_increase_target():
    decision = ReviewDecision("CONFIRM", "REDUCE", Decimal("1200"), "bigger")
    clamped = clamp_review(_candidate(), decision, current_quantity=Decimal("1000"))
    assert clamped.decision == "CONFIRM"
    assert clamped.target_quantity == Decimal("500")


def test_llm_cannot_weaken_exit():
    decision = ReviewDecision("CONFIRM", "WATCH", Decimal("800"), "hold instead")
    clamped = clamp_review(_candidate(action="EXIT", target="0"), decision, current_quantity=Decimal("1000"))
    assert clamped.action == "EXIT"
    assert clamped.target_quantity == Decimal("0")


def test_hard_stop_ignores_reject():
    decision = ReviewDecision("REJECT", "WATCH", None, "no")
    clamped = clamp_review(
        _candidate(action="EXIT", target="0", severity="hard"),
        decision,
        current_quantity=Decimal("1000"),
    )
    assert clamped.decision == "CONFIRM"
    assert clamped.action == "EXIT"
