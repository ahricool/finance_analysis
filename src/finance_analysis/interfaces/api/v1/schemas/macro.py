"""Typed US Macro transport contracts, inheriting the domain result fields."""

from finance_analysis.macro.models import MacroDashboard, MacroSeriesResult


class DashboardResponse(MacroDashboard):
    """Shared market state, explicit signal contributions, and data quality."""


class SeriesResponse(MacroSeriesResult):
    """Dated chart points and dependency coverage."""
