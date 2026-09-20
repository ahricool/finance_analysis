"""Portfolio warning isolation, per-lot risk, valuation universe, and incomplete NAV."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from finance_analysis.portfolio.models import (  # pragma: allowlist secret
    ResolvedAccount,
    ResolvedLot,
    ResolvedPortfolio,
    ResolvedPosition,
)
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import (  # pragma: allowlist secret
    DailyBar,
    LotRisk,
    PositionRisk,
    QuoteView,
)
from finance_analysis.trade_engine.position_risk import open_position_risk  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret
from finance_analysis.trade_engine.valuation import build_market_portfolio_context  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
POLICY = RiskPolicy(
    max_symbol_weight=Decimal("0.10"),
    max_gross_exposure=Decimal("0.50"),
    risk_per_symbol=Decimal("0.005"),
    total_open_risk=Decimal("0.02"),
)


def _position(*, market="CN", symbol="600519.SH", position_id="11", quantity="1000", enabled=True, lots=()):
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
        lots=lots,
        trade_engine_enabled=enabled,
    )


def _book(positions, *, cash="0", market="CN", quotes=None, daily=None):
    quotes = quotes or {item.symbol: QuoteView(Decimal("100"), NOW, True) for item in positions}
    daily = daily or {}
    portfolio = ResolvedPortfolio(
        uid=1,
        accounts=(ResolvedAccount("DB", 1, "1", market, market, Decimal(cash), "CNY" if market == "CN" else "USD"),),
        positions=tuple(positions),
    )
    return build_market_portfolio_context(portfolio, market=market, quotes=quotes, daily=daily)


def _run(state, *, now=NOW, cash="0", market="CN", positions=None, price="100", risks=None, quotes=None, daily=None):
    positions = positions or [_position(market=market)]
    quotes = quotes or {item.symbol: QuoteView(price=Decimal(price), quote_as_of=now, valid=True) for item in positions}
    book = _book(positions, cash=cash, market=market, quotes=quotes, daily=daily or {})
    return PortfolioRiskV1().evaluate_portfolio(
        book,
        risks or {},
        now=now,
        policy=POLICY,
        strategy_state=state,
    )


def test_per_lot_open_risk_does_not_collapse_stops():
    risk = PositionRisk(
        lots=(
            LotRisk("core", "CORE", Decimal("1000"), Decimal("100"), Decimal("120"), "A", Decimal("90"), Decimal("80")),
            LotRisk("addon", "ADDON", Decimal("500"), Decimal("109"), Decimal("112"), "A", Decimal("108"), Decimal("105")),
        )
    )
    assert open_position_risk(risk, Decimal("110")) == Decimal("21000")


def test_portfolio_risk_uses_per_lot_risk_for_symbol_and_total():
    lots = (
        ResolvedLot("core", "CORE", Decimal("1000"), Decimal("100"), NOW),
        ResolvedLot("addon", "ADDON", Decimal("500"), Decimal("109"), NOW),
    )
    position = _position(quantity="1500", lots=lots, market="US", symbol="AAPL.US", position_id="11")
    risk = PositionRisk(
        lots=(
            LotRisk("core", "CORE", Decimal("1000"), Decimal("100"), Decimal("120"), "A", Decimal("90"), None),
            LotRisk("addon", "ADDON", Decimal("500"), Decimal("109"), Decimal("112"), "A", Decimal("108"), None),
        )
    )
    quotes = {"AAPL.US": QuoteView(Decimal("110"), NOW, True)}
    book = _book([position], cash="0", market="US", quotes=quotes)
    assert open_position_risk(risk, Decimal("110")) == Decimal("21000")
    state = {}
    warnings = PortfolioRiskV1().evaluate_portfolio(
        book,
        {"11": risk},
        now=NOW,
        policy=POLICY,
        strategy_state=state,
    )
    kinds = {item.kind for item in warnings}
    assert "risk_per_symbol" in kinds
    assert "total_open_risk" in kinds
    risk_warning = next(item for item in warnings if item.kind == "risk_per_symbol")
    nav = Decimal(risk_warning.evidence["nav"])
    assert risk_warning.current == Decimal("21000") / nav
    collapsed = Decimal("1500") * (Decimal("110") - Decimal("108")) / nav
    assert risk_warning.current != collapsed


def test_cn_full_exposure_does_not_use_us_cash():
    cn_state, us_state = {}, {}
    cn = _run(cn_state, cash="0", market="CN", positions=[_position(quantity="10000")])
    us = _run(us_state, cash="1000000", market="US", positions=[], price="100")
    kinds = {item.kind for item in cn}
    assert "max_gross_exposure" in kinds
    assert us == []
    assert all(item.market == "CN" for item in cn)


def test_disabled_position_still_counts_in_nav_and_weight():
    aapl = _position(market="US", symbol="AAPL.US", position_id="11", quantity="2500", enabled=False)
    nvda = _position(market="US", symbol="NVDA.US", position_id="12", quantity="5000", enabled=True)
    quotes = {
        "AAPL.US": QuoteView(Decimal("200"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    book = _book([aapl, nvda], cash="0", market="US", quotes=quotes)
    assert book.nav == Decimal("1000000")
    assert book.market_values["12"] / book.nav == Decimal("0.5")
    assert [item.symbol for item in book.strategy_positions] == ["NVDA.US"]
    warnings = PortfolioRiskV1().evaluate_portfolio(book, {}, now=NOW, policy=POLICY, strategy_state={})
    weights = {item.symbol: item.current for item in warnings if item.kind == "max_symbol_weight"}
    assert weights["AAPL.US"] == Decimal("0.5")
    assert weights["NVDA.US"] == Decimal("0.5")


def test_missing_quote_falls_back_to_daily_close():
    position = _position(quantity="10")
    bars = [DailyBar(NOW.date(), Decimal("50"), Decimal("51"), Decimal("49"), Decimal("50"), 100)]
    quotes = {"600519.SH": QuoteView(Decimal("0"), None, False, True)}
    book = _book([position], cash="0", market="CN", quotes=quotes, daily={"600519.SH": bars})
    assert book.valuation_complete is True
    assert book.valuation_sources[position.position_id] == "DAILY_FALLBACK"
    assert book.nav == Decimal("500")
    warnings = PortfolioRiskV1().evaluate_portfolio(book, {}, now=NOW, policy=POLICY, strategy_state={})
    assert any(item.kind == "max_gross_exposure" for item in warnings)


def test_missing_quote_and_daily_marks_valuation_incomplete():
    priced = _position(symbol="600519.SH", position_id="11", quantity="10000")
    missing = _position(symbol="000001.SZ", position_id="12", quantity="10")
    quotes = {"600519.SH": QuoteView(Decimal("100"), NOW, True)}
    book = _book([priced, missing], cash="0", market="CN", quotes=quotes, daily={})
    assert book.valuation_complete is False
    assert book.nav is None
    state = {}
    warnings = PortfolioRiskV1().evaluate_portfolio(book, {}, now=NOW, policy=POLICY, strategy_state=state)
    assert warnings == []
    assert state["valuation_complete"] is False
    assert "max_symbol_weight" not in {item.kind for item in warnings}


def test_google_cash_is_excluded_from_trade_engine_nav():
    position = _position(market="US", symbol="AAPL.US", quantity="1")
    portfolio = ResolvedPortfolio(
        uid=1,
        accounts=(
            ResolvedAccount("DB", 1, "1", "US", "US", Decimal("100000"), "USD"),
            ResolvedAccount("GOOGLE", 1, "g1", "IB", "US", Decimal("100000"), "USD"),
        ),
        positions=(position,),
    )
    quotes = {"AAPL.US": QuoteView(Decimal("100"), NOW, True)}
    book = build_market_portfolio_context(portfolio, market="US", quotes=quotes, daily={})
    assert book.cash == Decimal("100000")
    assert book.nav == Decimal("100100")


def test_portfolio_warning_rearms_with_new_key():
    state = {}
    first = _run(state)
    assert first
    keys = {item.warning_key for item in first}
    again = _run(state)
    assert again == []
    recovered = _run(state, cash="10000000")
    assert recovered == []
    assert state.get("active_keys") == []
    later = NOW + timedelta(minutes=5)
    restarted = _run(state, now=later)
    new_keys = {item.warning_key for item in restarted}
    assert restarted
    assert new_keys.isdisjoint(keys)
    assert {item.kind for item in restarted} == {item.kind for item in first}


def test_warning_is_not_a_trade_proposal():
    warnings = _run({})
    assert warnings
    assert all(item.kind for item in warnings)
    assert not hasattr(warnings[0], "action") or getattr(warnings[0], "action", None) not in {"BUY", "ADD", "REDUCE", "EXIT"}


def test_shared_market_context_nav_matches_warning_evidence():
    position = _position(quantity="10000")
    book = _book([position], cash="0")
    warnings = PortfolioRiskV1().evaluate_portfolio(book, {}, now=NOW, policy=POLICY, strategy_state={})
    assert warnings
    assert Decimal(warnings[0].evidence["nav"]) == book.nav
