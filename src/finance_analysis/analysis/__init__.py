# -*- coding: utf-8 -*-
"""Stock analysis report generation package."""

from finance_analysis.analysis.stock_report_analyzer import (
    AnalysisResult,
    StockReportAnalyzer,
    apply_placeholder_fill,
    check_content_integrity,
    fill_chip_structure_if_needed,
    fill_price_position_if_needed,
    get_analyzer,
    get_stock_name_multi_source,
    stabilize_decision_with_structure,
)

__all__ = [
    "AnalysisResult",
    "StockReportAnalyzer",
    "apply_placeholder_fill",
    "check_content_integrity",
    "fill_chip_structure_if_needed",
    "fill_price_position_if_needed",
    "get_analyzer",
    "get_stock_name_multi_source",
    "stabilize_decision_with_structure",
]
