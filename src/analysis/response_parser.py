# -*- coding: utf-8 -*-
"""LLM response parsing helpers for stock reports."""

from src.analysis.stock_report_analyzer import StockReportAnalyzer


def parse_response(response_text: str, code: str, name: str):
    return StockReportAnalyzer()._parse_response(response_text, code, name)


def validate_json_response(text: str) -> None:
    StockReportAnalyzer()._validate_json_response(text)


__all__ = ["parse_response", "validate_json_response"]
