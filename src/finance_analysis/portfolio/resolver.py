# -*- coding: utf-8 -*-
"""Merge DB primary holdings with Google Sheet secondary holdings."""

from __future__ import annotations

from decimal import Decimal

from finance_analysis.database.repositories.portfolio import PortfolioRepository, _dec  # pragma: allowlist secret
from finance_analysis.holdings.models import HoldingsSnapshot, ParsedLeg, ParsedPosition  # pragma: allowlist secret
from finance_analysis.holdings.service import HoldingsService  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market  # pragma: allowlist secret
from finance_analysis.portfolio.models import (  # pragma: allowlist secret
    ResolvedAccount,
    ResolvedLot,
    ResolvedPortfolio,
    ResolvedPosition,
    currency_for_market,
)
from finance_analysis.portfolio.service import PortfolioService  # pragma: allowlist secret


def _google_symbol(position: ParsedPosition | ParsedLeg) -> str | None:
    raw = position.canonical_symbol or position.symbol
    if not raw:
        return None
    try:
        return canonical_symbol(raw)
    except Exception:
        return raw.strip().upper()


class PortfolioResolver:
    def __init__(
        self,
        *,
        portfolio: PortfolioService | None = None,
        holdings: HoldingsService | None = None,
        repository: PortfolioRepository | None = None,
    ) -> None:
        self.portfolio = portfolio or PortfolioService()
        self.holdings = holdings or HoldingsService()
        self.repository = repository or self.portfolio.repository

    def get_resolved_portfolio(self, uid: int, *, market: str | None = None) -> ResolvedPortfolio:
        self.portfolio.ensure_accounts(uid)
        snapshot = self.holdings.get_snapshot(uid=uid)
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
            db_keys: set[tuple[str, str]] = set()
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
                db_keys.add((row.market, row.symbol))
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
        google_positions, google_accounts, warnings, generation = self._from_google(uid, snapshot, db_keys, market)
        merged_accounts = list(resolved_accounts)
        seen_accounts = {item.account_id for item in merged_accounts}
        for account in google_accounts:
            if account.account_id not in seen_accounts:
                merged_accounts.append(account)
                seen_accounts.add(account.account_id)
        return ResolvedPortfolio(
            uid=uid,
            accounts=tuple(merged_accounts),
            positions=tuple(db_positions + google_positions),
            warnings=tuple(warnings),
            google_generation=generation,
        )

    def _from_google(
        self,
        uid: int,
        snapshot: HoldingsSnapshot | None,
        db_keys: set[tuple[str, str]],
        market: str | None,
    ) -> tuple[list[ResolvedPosition], list[ResolvedAccount], list[str], int | None]:
        if snapshot is None:
            return [], [], [], None
        warnings = list(snapshot.warnings)
        if snapshot.status != "VALID":
            warnings.append(f"google_snapshot_{snapshot.status.lower()}")
            return [], [], warnings, snapshot.generation
        accounts = [
            ResolvedAccount(
                source="GOOGLE",
                uid=uid,
                account_id=f"google:{item.account_id}",
                name=item.account_name,
                market=_guess_market(item.base_currency, snapshot),
                cash=item.cash or Decimal("0"),
                currency=item.base_currency,
            )
            for item in snapshot.accounts
        ]
        positions: list[ResolvedPosition] = []
        for position in snapshot.positions:
            symbol = _google_symbol(position)
            if not symbol:
                continue
            try:
                pos_market = infer_market(symbol).value
            except Exception:
                pos_market = "US"
            if market and pos_market != market:
                continue
            asset = (position.asset_type or "STOCK").upper()
            if (pos_market, symbol) in db_keys and asset != "OPTION":
                continue
            open_legs = [leg for leg in position.legs if (leg.status or "OPEN") == "OPEN" and leg.quantity > 0]
            if not open_legs:
                continue
            quantity = sum((leg.quantity for leg in open_legs), start=Decimal("0"))
            weighted = sum((leg.quantity * leg.entry_price for leg in open_legs), start=Decimal("0"))
            average = weighted / quantity if quantity else Decimal("0")
            coverage = "EXTERNAL_ONLY" if asset == "OPTION" else "EXTERNAL"
            lots = tuple(
                ResolvedLot(
                    lot_id=leg.leg_id,
                    role=leg.leg_role if leg.leg_role in {"CORE", "ADDON"} else "CORE",
                    quantity=leg.quantity,
                    entry_price=leg.entry_price,
                    entry_time=leg.entry_time,
                )
                for leg in open_legs
            )
            positions.append(
                ResolvedPosition(
                    source="GOOGLE",
                    coverage=coverage,
                    uid=uid,
                    market=pos_market,
                    account_id=f"google:{position.account_id}",
                    position_id=f"google:{position.position_id}",
                    symbol=symbol,
                    asset_type=asset,
                    quantity=quantity,
                    average_cost=average,
                    opened_at=min((leg.entry_time for leg in open_legs), default=None),
                    lots=lots,
                )
            )
        for leg in snapshot.uncovered_legs:
            if (leg.status or "OPEN") != "OPEN" or leg.quantity <= 0:
                continue
            symbol = _google_symbol(leg)
            if not symbol:
                continue
            try:
                pos_market = infer_market(symbol).value
            except Exception:
                pos_market = "US"
            if market and pos_market != market:
                continue
            asset = (leg.asset_type or "OPTION").upper()
            if asset != "OPTION" and (pos_market, symbol) in db_keys:
                continue
            positions.append(
                ResolvedPosition(
                    source="GOOGLE",
                    coverage="EXTERNAL_ONLY",
                    uid=uid,
                    market=pos_market,
                    account_id=f"google:{leg.account_id}",
                    position_id=f"google:{leg.position_id}",
                    symbol=symbol,
                    asset_type=asset or "OPTION",
                    quantity=leg.quantity,
                    average_cost=leg.entry_price,
                    opened_at=leg.entry_time,
                    lots=(
                        ResolvedLot(
                            lot_id=leg.leg_id,
                            role=leg.leg_role if leg.leg_role in {"CORE", "ADDON"} else "CORE",
                            quantity=leg.quantity,
                            entry_price=leg.entry_price,
                            entry_time=leg.entry_time,
                        ),
                    ),
                )
            )
        return positions, accounts, warnings, snapshot.generation


def _guess_market(currency: str, snapshot: HoldingsSnapshot) -> str:
    if currency == "CNY":
        return "CN"
    if currency == "USD":
        return "US"
    for position in snapshot.positions:
        symbol = _google_symbol(position)
        if symbol:
            return infer_market(symbol).value
    return "US"
