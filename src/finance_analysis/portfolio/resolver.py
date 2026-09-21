# -*- coding: utf-8 -*-
"""Build the DB-only portfolio context used by Trade Engine and Holdings."""

from __future__ import annotations

from finance_analysis.database.repositories.portfolio import PortfolioRepository, _dec  # pragma: allowlist secret
from finance_analysis.portfolio.models import (  # pragma: allowlist secret
    ResolvedAccount,
    ResolvedLot,
    ResolvedPortfolio,
    ResolvedPosition,
    currency_for_market,
)
from finance_analysis.portfolio.service import PortfolioService  # pragma: allowlist secret


class PortfolioResolver:
    def __init__(
        self,
        *,
        portfolio: PortfolioService | None = None,
        repository: PortfolioRepository | None = None,
    ) -> None:
        self.portfolio = portfolio or PortfolioService()
        self.repository = repository or self.portfolio.repository

    def get_resolved_portfolio(self, uid: int, *, market: str | None = None) -> ResolvedPortfolio:
        self.portfolio.ensure_accounts(uid)
        with self.repository.db.get_session() as session:
            accounts = self.repository.list_accounts(session, uid=uid, market=market)
            positions = self.repository.list_open_positions(session, uid=uid, market=market)
            lots_map = self.repository.list_lots(session, position_ids=[row.id for row in positions])
            resolved_accounts = [
                ResolvedAccount(
                    source="DB",
                    uid=uid,
                    account_id=str(row.id),
                    name=row.name,
                    market=row.market,
                    cash=_dec(row.cash),
                    currency=currency_for_market(row.market),
                )
                for row in accounts
            ]
            db_positions: list[ResolvedPosition] = []
            for row in positions:
                lots = tuple(
                    ResolvedLot(
                        lot_id=str(lot.id),
                        role=lot.role,  # type: ignore[arg-type]
                        quantity=_dec(lot.remaining_quantity),
                        entry_price=_dec(lot.entry_price),
                        entry_time=lot.entry_time,
                    )
                    for lot in lots_map.get(row.id, [])
                    if _dec(lot.remaining_quantity) > 0
                )
                had_addon = any(lot.role == "ADDON" for lot in lots_map.get(row.id, []))
                db_positions.append(
                    ResolvedPosition(
                        source="DB",
                        coverage="DB",
                        uid=uid,
                        market=row.market,
                        account_id=str(row.account_id),
                        position_id=str(row.id),
                        symbol=row.symbol,
                        asset_type=row.asset_type,
                        quantity=_dec(row.quantity),
                        average_cost=_dec(row.average_cost),
                        opened_at=row.opened_at,
                        lots=lots,
                        had_addon=had_addon,
                        trade_engine_enabled=True
                        if getattr(row, "trade_engine_enabled", None) is None
                        else bool(row.trade_engine_enabled),
                    )
                )
        return ResolvedPortfolio(
            uid=uid,
            accounts=tuple(resolved_accounts),
            positions=tuple(db_positions),
        )
