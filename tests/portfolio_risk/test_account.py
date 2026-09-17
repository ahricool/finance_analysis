"""Account constraints rewrite final targets. Synthetic quotes only."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.portfolio_risk.account import AccountView, apply_account_constraints, merge_account_targets  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.exits import LegInput, PositionInput, PositionState, QuoteView, evaluate_position_exit  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
POLICY = RiskPolicy()


def test_max_symbol_weight_overrides_technical_hold():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    position = PositionInput(
        "a1",
        "p1",
        "600519.SH",
        (LegInput("core", "CORE", Decimal("1000"), Decimal("20"), datetime(2026, 9, 14, 9, 35, tzinfo=SH)),),
    )
    quote = QuoteView(price=Decimal("20"), quote_as_of=now, valid=True)
    exit_result = evaluate_position_exit(
        position,
        quote=quote,
        bars=[],
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
    )
    assert exit_result.plan.action == "HOLD" or exit_result.action == "HOLD"
    assert exit_result.position_target == Decimal("1000")
    account = AccountView("a1", "CNY", Decimal("100000"), True)
    risks = apply_account_constraints(
        account=account,
        positions=[(position, exit_result, quote)],
        policy=POLICY,
        currencies={"600519.SH": "CNY"},
    )
    risk = risks[("a1", "p1")]
    assert risk.target_quantity == Decimal("500")
    assert "max_symbol_weight" in risk.unmet
    merged = merge_account_targets(position, exit_result, risk)
    assert merged.position_target == Decimal("500")
    assert merged.plan.status == "PENDING"
    assert merged.plan.action == "REDUCE"
    assert any(event["event_type"] == "ACCOUNT_CONSTRAINT" for event in merged.events)
    assert merged.evidence["current_risk"] is not None
    assert merged.evidence["post_plan_risk"] is not None
    assert merged.evidence["advice_not_fill"] is True
