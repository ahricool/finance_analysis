"""Virtual position arithmetic, without accounts or orders."""

from dataclasses import replace
from decimal import Decimal

from finance_analysis.crypto.models import StrategyState


def change_position(state: StrategyState, target: Decimal, price: Decimal, at) -> StrategyState:
    before = state.position_pct
    if not target.is_finite() or not Decimal(0) <= target <= Decimal(1):
        raise ValueError("Position must be between zero and one")
    if not price.is_finite() or price <= 0:
        raise ValueError("Execution price must be positive")
    if target == 0:
        return StrategyState(strategy_key=state.strategy_key, symbol=state.symbol, updated_at=at)
    average = state.average_entry_price
    if target > before:
        if before > 0 and average is None:
            raise ValueError("Existing position has no average cost")
        average = (before * (average or Decimal(0)) + (target - before) * price) / target
    return replace(
        state,
        position_pct=target,
        position_state="LONG",
        average_entry_price=average,
        entry_price=average,
        highest_price_since_entry=price if before == 0 else state.highest_price_since_entry,
        entry_time=state.entry_time if before > 0 else at,
        updated_at=at,
    )
