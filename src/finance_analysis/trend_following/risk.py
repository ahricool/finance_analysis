"""ATR-based theoretical risk controls, independent of user accounts."""

from __future__ import annotations

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig


def initial_risk_levels(
    entry: float,
    atr: float,
    structure_low: float,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> dict[str, float]:
    atr_stop = entry - config.initial_stop_atr * atr
    structure_stop = structure_low - config.structure_stop_buffer_atr * atr
    valid_structure = structure_stop if 0 < structure_stop < entry else atr_stop
    initial_stop = max(atr_stop, valid_structure)
    if not 0 < initial_stop < entry:
        initial_stop = max(entry * 0.01, min(entry - 1e-8, atr_stop))
    stop_distance_pct = (entry - initial_stop) / entry
    calculated = config.risk_per_trade / stop_distance_pct
    initial_weight = min(calculated, config.single_stock_max_weight)
    return {
        "initial_stop": round(initial_stop, 6),
        "stop_distance_pct": stop_distance_pct,
        "suggested_initial_weight": initial_weight,
        "suggested_max_weight": config.single_stock_max_weight,
    }


def trailing_stop(highest_close: float, atr: float, config: TrendFollowingConfig = DEFAULT_CONFIG) -> float:
    return round(highest_close - config.trailing_stop_atr * atr, 6)


def next_add_price(last_add_price: float, atr: float, config: TrendFollowingConfig = DEFAULT_CONFIG) -> float:
    return round(last_add_price + config.pyramid_interval_atr * atr, 6)


__all__ = ["initial_risk_levels", "next_add_price", "trailing_stop"]
