# -*- coding: utf-8 -*-
"""Stock report prompt constants."""

from src.analysis.stock_report_analyzer import StockReportAnalyzer

SYSTEM_PROMPT = StockReportAnalyzer.SYSTEM_PROMPT
LEGACY_DEFAULT_SYSTEM_PROMPT = StockReportAnalyzer.LEGACY_DEFAULT_SYSTEM_PROMPT
TEXT_SYSTEM_PROMPT = StockReportAnalyzer.TEXT_SYSTEM_PROMPT

__all__ = [
    "LEGACY_DEFAULT_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "TEXT_SYSTEM_PROMPT",
]
