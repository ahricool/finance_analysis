"""DB portfolio resolver is the only holdings context builder."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.portfolio.context import render_portfolio_context  # pragma: allowlist secret
from finance_analysis.portfolio.resolver import PortfolioResolver  # pragma: allowlist secret


class FakePortfolio:
    def ensure_accounts(self, uid):
        return []

    repository = SimpleNamespace(db=SimpleNamespace(get_session=None))


class FakeRepo:
    def list_accounts(self, session, *, uid, market=None):
        return [SimpleNamespace(id=1, uid=uid, name="美股账户", market="US", cash=Decimal("350000"))]

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
                trade_engine_enabled=True,
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


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_resolver_reads_db_positions_only():
    repo = FakeRepo()
    repo.db = SimpleNamespace(get_session=lambda: _Null())
    resolver = PortfolioResolver(portfolio=FakePortfolio(), repository=repo)
    portfolio = resolver.get_resolved_portfolio(1, market="US")
    assert len(portfolio.positions) == 1
    aapl = portfolio.positions[0]
    assert aapl.source == "DB"
    assert aapl.symbol == "AAPL.US"
    assert aapl.quantity == Decimal("100")
    assert portfolio.db_cash("US") == Decimal("350000")
    text = render_portfolio_context(portfolio)
    assert "AAPL.US" in text
    assert "source=DB" in text
    assert "GOOGLE" not in text
