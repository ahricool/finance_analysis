# -*- coding: utf-8 -*-
"""Natural-language portfolio context. Marks DB vs Google sources."""

from __future__ import annotations

from finance_analysis.portfolio.models import ResolvedPortfolio  # pragma: allowlist secret


def render_portfolio_context(portfolio: ResolvedPortfolio) -> str:
    lines = [f"持仓 uid={portfolio.uid} google_generation={portfolio.google_generation or '-'}"]
    if portfolio.warnings:
        lines.append("warnings=" + ";".join(portfolio.warnings))
    for account in portfolio.accounts:
        lines.append(
            f"账户 {account.name} {account.market} cash={format(account.cash, 'f')} "
            f"currency={account.currency} [{account.source}]"
        )
    for position in portfolio.positions:
        lines.append(
            f"{position.symbol} {format(position.quantity, 'f')}股 @{format(position.average_cost, 'f')} "
            f"{position.asset_type} [{position.source}] coverage={position.coverage}"
        )
        for lot in position.lots:
            lines.append(
                f"  {lot.role} {lot.lot_id} qty={format(lot.quantity, 'f')} entry={format(lot.entry_price, 'f')}"
            )
    return "\n".join(lines)
