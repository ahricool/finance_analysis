# -*- coding: utf-8 -*-
"""A-share snapshot breadth used by pre-close review, not Trade Engine."""

from datetime import date

from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.metrics import compute_market_breadth  # pragma: allowlist secret


def _row(code, name, price, pre_close, *, open_=None, high=None, low=None, change_pct=None, amount=1.0e8):
    if change_pct is None and pre_close:
        change_pct = round((price - pre_close) / pre_close * 100, 4)
    return {
        "code": code,
        "name": name,
        "price": price,
        "pre_close": pre_close,
        "open": open_ if open_ is not None else pre_close,
        "high": high if high is not None else max(price, open_ or pre_close),
        "low": low if low is not None else min(price, open_ or pre_close),
        "change_pct": change_pct,
        "amount": amount,
    }


def test_market_breadth_counts_up_down_and_limits():
    rows = [
        _row("600000", "浦发银行", 11.0, 10.0),
        _row("600001", "示例A", 9.0, 10.0),
        _row("600002", "示例B", 10.5, 10.0),
        _row("600003", "示例C", 9.8, 10.0),
        _row("600004", "示例D", 10.0, 10.0),
    ]
    breadth = compute_market_breadth(rows, date(2026, 6, 24))
    assert breadth["up_count"] == 2
    assert breadth["down_count"] == 2
    assert breadth["flat_count"] == 1
    assert breadth["limit_up_count"] == 1
    assert breadth["limit_down_count"] == 1


def test_etf_excluded_from_limit_statistics():
    rows = [_row("510300", "沪深300ETF", 4.4, 4.0, high=4.4)]
    breadth = compute_market_breadth(rows, date(2026, 6, 24))
    assert breadth["counted_symbols"] == 0
    assert breadth["limit_up_count"] == 0
