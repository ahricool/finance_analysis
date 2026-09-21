"""Portfolio Risk Facts, per-lot risk, valuation universe, and incomplete NAV."""

from datetime import datetime, timezone
from decimal import Decimal

from finance_analysis.portfolio.models import (  # pragma: allowlist secret
    ResolvedAccount,
    ResolvedLot,
    ResolvedPortfolio,
    ResolvedPosition,
)
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import DailyBar, LotRisk, PositionRisk, QuoteView  # pragma: allowlist secret
from finance_analysis.trade_engine.position_risk import compute_position_risk, open_position_risk  # pragma: allowlist secret
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


def _facts(*, cash="0", market="CN", positions=None, price="100", risks=None, quotes=None, daily=None):
    positions = positions or [_position(market=market)]
    quotes = quotes or {item.symbol: QuoteView(price=Decimal(price), quote_as_of=NOW, valid=True) for item in positions}
    book = _book(positions, cash=cash, market=market, quotes=quotes, daily=daily or {})
    return PortfolioRiskV1().evaluate_portfolio(book, risks or {}, policy=POLICY), book


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
    facts, book = _facts(cash="0", market="US", positions=[position], quotes=quotes, risks={"11": risk})
    nav = book.nav
    assert facts.positions["AAPL.US"].open_risk == Decimal("21000") / nav
    collapsed = Decimal("1500") * (Decimal("110") - Decimal("108")) / nav
    assert facts.positions["AAPL.US"].open_risk != collapsed
    assert facts.total_open_risk == Decimal("21000") / nav


def test_cn_full_exposure_does_not_use_us_cash():
    cn, cn_book = _facts(cash="0", market="CN", positions=[_position(quantity="10000")])
    us, us_book = _facts(cash="1000000", market="US", positions=[], price="100")
    assert cn.gross_exposure is not None and cn.gross_exposure > cn.max_gross_exposure
    assert us_book.positions == ()
    assert cn.market == "CN"


def test_disabled_position_still_counts_in_nav_and_weight():
    aapl = _position(market="US", symbol="AAPL.US", position_id="11", quantity="2500", enabled=False)
    nvda = _position(market="US", symbol="NVDA.US", position_id="12", quantity="5000", enabled=True)
    quotes = {
        "AAPL.US": QuoteView(Decimal("200"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    facts, book = _facts(cash="0", market="US", positions=[aapl, nvda], quotes=quotes)
    assert book.nav == Decimal("1000000")
    assert book.market_values["12"] / book.nav == Decimal("0.5")
    assert [item.symbol for item in book.strategy_positions] == ["NVDA.US"]
    assert facts.positions["AAPL.US"].weight == Decimal("0.5")
    assert facts.positions["NVDA.US"].weight == Decimal("0.5")


def test_missing_quote_falls_back_to_daily_close():
    position = _position(quantity="10")
    bars = [DailyBar(NOW.date(), Decimal("50"), Decimal("51"), Decimal("49"), Decimal("50"), 100)]
    quotes = {"600519.SH": QuoteView(None, None, False, True)}
    facts, book = _facts(cash="0", market="CN", positions=[position], quotes=quotes, daily={"600519.SH": bars})
    assert book.valuation_complete is True
    assert book.valuation_sources[position.position_id] == "DAILY_FALLBACK"
    assert book.nav == Decimal("500")
    assert facts.gross_exposure == Decimal("1")


def test_missing_quote_and_daily_marks_valuation_incomplete():
    priced = _position(symbol="600519.SH", position_id="11", quantity="10000")
    missing = _position(symbol="000001.SZ", position_id="12", quantity="10")
    quotes = {"600519.SH": QuoteView(Decimal("100"), NOW, True)}
    facts, book = _facts(cash="0", market="CN", positions=[priced, missing], quotes=quotes, daily={})
    assert book.valuation_complete is False
    assert book.nav is None
    assert facts.valuation_complete is False
    assert facts.gross_exposure is None


def test_position_risk_is_stateless_and_uses_full_history_high():
    lot = ResolvedLot("core", "CORE", Decimal("1000"), Decimal("100"), datetime(2026, 6, 2, tzinfo=timezone.utc))
    position = _position(lots=(lot,))
    early = [DailyBar(datetime(2026, 6, 10, tzinfo=timezone.utc).date(), Decimal("100"), Decimal("140"), Decimal("99"), Decimal("140"), 1)]
    later = early + [
        DailyBar(datetime(2026, 9, 1, tzinfo=timezone.utc).date(), Decimal("110"), Decimal("112"), Decimal("108"), Decimal("110"), 1)
    ]
    first = compute_position_risk(position, later, POLICY)
    second = compute_position_risk(position, later, POLICY)
    assert first.high_watermark == second.high_watermark == Decimal("140")
    assert first.active_stop == second.active_stop
    truncated = compute_position_risk(position, later[-1:], POLICY)
    assert truncated.high_watermark == Decimal("110")
