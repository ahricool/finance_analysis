"""Fund/index constraints must survive changes to report input providers."""

import pytest

from finance_analysis.stocks.classification import is_index_or_etf


@pytest.mark.parametrize(
    "code,name,expected",
    [
        ("510300.SH", "沪深300", True),
        ("159915.SZ", "创业板", True),
        ("SPX", "S&P 500", True),
        ("SPY.US", "SPDR S&P 500 ETF Trust", True),
        ("02800.HK", "Tracker Fund", True),
        ("AAPL.US", "Apple", False),
        ("600519.SH", "贵州茅台", False),
        ("", "ETF", False),
    ],
)
def test_classification_preserves_report_risk_scope(code, name, expected):
    assert is_index_or_etf(code, name) is expected
