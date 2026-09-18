# -*- coding: utf-8 -*-
"""Deterministic holdings text context. No LLM."""

from __future__ import annotations

from finance_analysis.holdings.models import HoldingsSnapshot  # pragma: allowlist secret


def render_holdings_context(snapshot: HoldingsSnapshot) -> str:
    lines = [
        f"持仓快照 generation={snapshot.generation} hash={snapshot.content_hash[:12]}",
        f"读取时间 fetched_at={snapshot.fetched_at.isoformat()} timezone={snapshot.timezone}",
        f"状态={snapshot.status}",
    ]
    if snapshot.rejection_code:
        lines.append(f"拒绝={snapshot.rejection_code}")
    for account in snapshot.accounts:
        nav = format(account.net_asset, "f") if account.net_asset is not None else "未知"
        lines.append(
            f"账户 {account.account_id} {account.account_name} 币种={account.base_currency} "
            f"净资产={nav} 完整={account.positions_complete} 校验={account.validity}"
        )
    for position in snapshot.positions:
        total = sum((leg.quantity for leg in position.legs if leg.status == "OPEN"), start=position.legs[0].quantity * 0)
        total = sum(leg.quantity for leg in position.legs if leg.status == "OPEN")
        lines.append(
            f"仓位 {position.account_id}/{position.position_id} {position.symbol} 总数量={format(total, 'f')}"
        )
        for leg in position.legs:
            lines.append(
                f"  {leg.leg_role} {leg.leg_id} qty={format(leg.quantity, 'f')} "
                f"entry={format(leg.entry_price, 'f')} status={leg.status} coverage={leg.coverage}"
            )
    if snapshot.uncovered_legs:
        lines.append(f"未覆盖腿 {len(snapshot.uncovered_legs)} 条，不按零计入也不从分母剔除")
    return "\n".join(lines)
