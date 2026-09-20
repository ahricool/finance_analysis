"""DB wins over Google for the same canonical symbol; OPTION stays external."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.holdings.models import HoldingsSnapshot, ParsedAccount, ParsedLeg, ParsedPosition  # pragma: allowlist secret
from finance_analysis.portfolio.context import render_portfolio_context  # pragma: allowlist secret
from finance_analysis.portfolio.resolver import PortfolioResolver  # pragma: allowlist secret


class FakePortfolio:
    def ensure_accounts(self, uid):
        return []

    repository = SimpleNamespace(db=SimpleNamespace(get_session=None))


class FakeRepo:
    def list_accounts(self, session, *, uid, market=None):
        return [
            SimpleNamespace(id=1, uid=uid, name="美股账户", market="US", cash=Decimal("0")),
        ]

    def list_open_positions(self, session, *, uid, market=None):
        return [
            SimpleNamespace(
                id=11,
                uid=uid,
                account_id=1,
                market="US",
                symbol="AAPL.US",
                asset_type="STOCK",
                quantity=Decimal("100"),
                average_cost=Decimal("190"),
                opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ]

    def list_lots(self, session, *, position_ids):
        return {
            11: [
                SimpleNamespace(
                    id=1,
                    role="CORE",
                    remaining_quantity=Decimal("100"),
                    entry_price=Decimal("190"),
                    entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            ]
        }


class FakeHoldings:
    def get_snapshot(self, uid):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        return HoldingsSnapshot(
            uid=uid,
            source_id=1,
            spreadsheet_id="sheet",
            generation=2,
            content_hash="abc",
            fetched_at=now,
            timezone="UTC",
            status="VALID",
            accounts=[
                ParsedAccount(
                    account_id="g1",
                    account_name="IB",
                    base_currency="USD",
                    positions_complete=True,
                    cash=Decimal("0"),
                )
            ],
            positions=[
                ParsedPosition(
                    account_id="g1",
                    position_id="aapl",
                    symbol="AAPL.US",
                    canonical_symbol="AAPL.US",
                    asset_type="STOCK",
                    legs=[
                        ParsedLeg(
                            account_id="g1",
                            position_id="aapl",
                            leg_id="core",
                            leg_role="CORE",
                            symbol="AAPL.US",
                            canonical_symbol="AAPL.US",
                            asset_type="STOCK",
                            quantity=Decimal("200"),
                            entry_price=Decimal("180"),
                            entry_time=now,
                            status="OPEN",
                        )
                    ],
                ),
                ParsedPosition(
                    account_id="g1",
                    position_id="msft",
                    symbol="MSFT.US",
                    canonical_symbol="MSFT.US",
                    asset_type="STOCK",
                    legs=[
                        ParsedLeg(
                            account_id="g1",
                            position_id="msft",
                            leg_id="core",
                            leg_role="CORE",
                            symbol="MSFT.US",
                            canonical_symbol="MSFT.US",
                            asset_type="STOCK",
                            quantity=Decimal("50"),
                            entry_price=Decimal("400"),
                            entry_time=now,
                            status="OPEN",
                        )
                    ],
                ),
                ParsedPosition(
                    account_id="g1",
                    position_id="opt",
                    symbol="AAPL 260918C200",
                    canonical_symbol="AAPL.US",
                    asset_type="OPTION",
                    legs=[
                        ParsedLeg(
                            account_id="g1",
                            position_id="opt",
                            leg_id="call",
                            leg_role="CORE",
                            symbol="AAPL 260918C200",
                            canonical_symbol="AAPL.US",
                            asset_type="OPTION",
                            quantity=Decimal("1"),
                            entry_price=Decimal("3"),
                            entry_time=now,
                            status="OPEN",
                        )
                    ],
                ),
            ],
        )


def test_db_wins_same_symbol_and_google_fills_missing_stock():
    repo = FakeRepo()
    repo.db = SimpleNamespace(get_session=lambda: _Null())
    resolver = PortfolioResolver(portfolio=FakePortfolio(), holdings=FakeHoldings(), repository=repo)
    portfolio = resolver.get_resolved_portfolio(1, market="US")
    by_symbol = {}
    for item in portfolio.positions:
        by_symbol.setdefault(item.symbol, []).append(item)
    aapl = [item for item in portfolio.positions if item.symbol == "AAPL.US" and item.asset_type == "STOCK"]
    assert len(aapl) == 1
    assert aapl[0].source == "DB"
    assert aapl[0].quantity == Decimal("100")
    msft = next(item for item in portfolio.positions if item.symbol == "MSFT.US")
    assert msft.source == "GOOGLE"
    assert msft.quantity == Decimal("50")
    option = next(item for item in portfolio.positions if item.asset_type == "OPTION")
    assert option.coverage == "EXTERNAL_ONLY"
    assert option.trade_engine_eligible is False
    text = render_portfolio_context(portfolio)
    assert "[DB]" in text
    assert "[GOOGLE]" in text


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
