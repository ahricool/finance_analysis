"""Portfolio warning isolation, re-arm, and unique episode keys."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from finance_analysis.portfolio.models import ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import QuoteView  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)


def _position(*, market="CN", symbol="600519.SH", position_id="11", quantity="1000"):
    return ResolvedPosition(
        source="DB",
        coverage="DB",
        uid=1,
        market=market,
        account_id="1" if market == "CN" else "2",
        position_id=position_id,
        symbol=symbol,
        asset_type="STOCK",
        quantity=Decimal(quantity),
        average_cost=Decimal("10"),
    )


def _run(state, *, now=NOW, cash="0", market="CN", positions=None, price="100"):
    positions = positions or [_position(market=market)]
    quotes = {item.symbol: QuoteView(price=Decimal(price), quote_as_of=now, valid=True) for item in positions}
    return PortfolioRiskV1().evaluate_portfolio(
        positions,
        quotes,
        {},
        cash=Decimal(cash),
        market=market,
        now=now,
        policy=RiskPolicy(max_symbol_weight=Decimal("0.10"), max_gross_exposure=Decimal("0.50")),
        strategy_state=state,
    )


def test_cn_full_exposure_does_not_use_us_cash():
    cn_state, us_state = {}, {}
    cn = _run(cn_state, cash="0", market="CN", positions=[_position(quantity="10000")])
    us = _run(
        us_state,
        cash="1000000",
        market="US",
        positions=[],
        price="100",
    )
    kinds = {item.kind for item in cn}
    assert "max_gross_exposure" in kinds
    assert us == []
    assert all(item.market == "CN" for item in cn)


def test_portfolio_warning_rearms_with_new_key():
    state = {}
    first = _run(state)
    assert first
    assert {item.kind for item in first}
    keys = {item.warning_key for item in first}
    again = _run(state)
    assert again == []
    recovered = _run(state, cash="10000000")
    assert recovered == []
    assert state.get("active_keys") == []
    later = NOW + timedelta(minutes=5)
    restarted = _run(state, now=later)
    assert restarted
    new_keys = {item.warning_key for item in restarted}
    assert new_keys.isdisjoint(keys)
    assert {item.kind for item in restarted} == {item.kind for item in first}


def test_warning_is_not_a_trade_proposal():
    warnings = _run({})
    assert warnings
    assert all(item.kind for item in warnings)
    assert not hasattr(warnings[0], "action") or getattr(warnings[0], "action", None) not in {"BUY", "ADD", "REDUCE", "EXIT"}
