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


def _round_account(items, account, policy, states):
    evaluated = []
    for index, (position, quote) in enumerate(items):
        exit_result = evaluate_position_exit(
            position,
            quote=quote,
            bars=[],
            state=states[index],
            policy=policy,
            now=quote.quote_as_of,
            market="CN",
        )
        evaluated.append((position, exit_result, quote))
    risks = apply_account_constraints(
        account=account,
        positions=evaluated,
        policy=policy,
        currencies={position.symbol: "CNY" for position, _quote in items},
    )
    merged = []
    for position, exit_result, _quote in evaluated:
        merged.append(merge_account_targets(position, exit_result, risks[(position.account_id, position.position_id)]))
    return merged, risks


def test_account_budget_is_idempotent_across_ten_identical_evaluations():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    policy = RiskPolicy()
    account = AccountView("a1", "CNY", Decimal("1000000"), True)
    items = []
    for index in range(6):
        position = PositionInput(
            "a1",
            f"p{index}",
            f"60000{index}.SH",
            (LegInput("core", "CORE", Decimal("1000"), Decimal("100"), now, initial_stop=Decimal("96")),),
        )
        quote = QuoteView(price=Decimal("100"), quote_as_of=now, valid=True)
        items.append((position, quote))
    states = [PositionState() for _ in items]
    totals = []
    revisions = []
    event_counts = []
    post_risks = []
    post_values = []
    for _ in range(10):
        merged, risks = _round_account(items, account, policy, states)
        states = [item.state for item in merged]
        total = sum((item.position_target for item in merged), start=Decimal("0"))
        totals.append(total)
        revisions.append(tuple(item.plan.revision for item in merged))
        event_counts.append(sum(event["event_type"] == "ACCOUNT_CONSTRAINT" for item in merged for event in item.events))
        post_risks.append(sum((risks[key].post_plan_risk or Decimal("0") for key in risks), start=Decimal("0")))
        post_values.append(sum((item.position_target * Decimal("100") for item in merged), start=Decimal("0")))
    assert totals[0] == Decimal("5000")
    assert all(total == totals[0] for total in totals)
    assert all(rev == revisions[0] for rev in revisions)
    assert event_counts[0] >= 1
    assert all(count == 0 for count in event_counts[1:])
    assert post_values[0] <= Decimal("500000")
    assert post_risks[0] <= Decimal("20000")
    assert post_values[0] == Decimal("500000")
    assert post_risks[0] == Decimal("20000")


def test_account_risk_cut_uses_per_leg_stops_and_addon_first():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    policy = RiskPolicy(
        max_symbol_weight=Decimal("1"),
        risk_per_symbol=Decimal("1"),
        max_gross_exposure=Decimal("2"),
        total_open_risk=Decimal("0.02"),
    )
    account = AccountView("a1", "CNY", Decimal("100000"), True)
    position = PositionInput(
        "a1",
        "p1",
        "600519.SH",
        (
            LegInput("core", "CORE", Decimal("1000"), Decimal("100"), now, initial_stop=Decimal("96")),
            LegInput(
                "addon",
                "ADDON",
                Decimal("1000"),
                Decimal("100"),
                now,
                initial_stop=Decimal("98"),
            ),
        ),
    )
    quote = QuoteView(price=Decimal("100"), quote_as_of=now, valid=True)
    merged, risks = _round_account([(position, quote)], account, policy, [PositionState()])
    result = merged[0]
    risk = risks[("a1", "p1")]
    by_id = {item.leg_id: item.target_quantity for item in result.leg_exits}
    assert by_id["addon"] == Decimal("0")
    assert by_id["core"] == Decimal("500")
    assert result.position_target == Decimal("500")
    assert risk.post_plan_risk == Decimal("2000")
    assert risk.post_plan_risk <= policy.total_open_risk * account.net_asset
