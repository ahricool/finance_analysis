"""Rule-based, market-aware ETF momentum rotation domain."""

from finance_analysis.etf_rotation.risk import calculate_stop_loss_pct, calculate_suggested_stop_price
from finance_analysis.etf_rotation.universe import CN_ETF_UNIVERSE, ETF_UNIVERSE, US_ETF_UNIVERSE, enabled_etfs

__all__ = [
    "CN_ETF_UNIVERSE",
    "ETF_UNIVERSE",
    "US_ETF_UNIVERSE",
    "calculate_stop_loss_pct",
    "calculate_suggested_stop_price",
    "enabled_etfs",
]
