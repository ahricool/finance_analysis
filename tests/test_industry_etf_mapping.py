"""Industry proxies must stay inside Rotation pools and preserve missing evidence."""

import runpy
from pathlib import Path

import pytest

from finance_analysis.database.index_etf import INDEX_ETF_MEMBERS
from finance_analysis.stocks.industry_etf import CN_INDUSTRY_ETF, US_INDUSTRY_ETF, resolve_industry_etf

summarize = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/report_industry_etf_coverage.py"))[
    "summarize"
]


def test_every_target_belongs_to_same_market_rotation_pool():
    for market, registry in (("CN", CN_INDUSTRY_ETF), ("US", US_INDUSTRY_ETF)):
        allowed = {
            row[0]
            for row in INDEX_ETF_MEMBERS[market]
            if row[2] not in {"BROAD_INDEX", "OVERSEAS_INDEX", "BROAD_MARKET"}
        }
        assert {entry.etf_code for entry in registry.values() if entry.etf_code} <= allowed
        assert all(
            entry.reason and any("\u4e00" <= char <= "\u9fff" for char in entry.reason) for entry in registry.values()
        )


@pytest.mark.parametrize(
    "market,industry,sector,expected",
    [
        ("US", "Semiconductors", "Technology", "SMH.US"),
        ("US", "Consumer Electronics", "Technology", "XLK.US"),
        ("US", "Banks—Regional", "Financial Services", "KRE.US"),
        ("US", "Shell Companies", "Financial Services", None),
        ("US", "REIT—Mortgage", "Real Estate", "XLF.US"),
        ("US", "Thermal Coal", "Energy", "XLE.US"),
        ("US", "Education & Training Services", "Consumer Defensive", "XLY.US"),
        ("US", "Semiconductors", "Healthcare", None),
        ("US", "Unknown new theme", "Technology", None),
        ("CN", "881155.TI", None, "512800.SH"),
        ("CN", "884218.TI", None, "562500.SH"),
        ("CN", "881171.TI", None, "562500.SH"),  # 自动化用机器人产业链近似代理。
        ("CN", "881125.TI", None, "515030.SH"),  # 整车用新能源车近似观察汽车景气。
        ("CN", "881112.TI", None, "512400.SH"),  # 钢铁用金属资源周期近似代理。
        ("CN", "半导体", None, None),  # CN只接受代码，不能按自由文本猜测。
        ("HK", "Semiconductors", "Technology", None),
    ],
)
def test_reviewed_semantics_and_unknown_categories(market, industry, sector, expected):
    result = resolve_industry_etf(market, industry, sector=sector)
    assert result.etf_code == expected
    assert result.reason


def test_coverage_counts_unique_stocks_and_keeps_real_denominators():
    def stock(market, code, status="ACTIVE", classification=None):
        return dict(market=market, code=code, listing_status=status, metadata={"classification": classification})

    stocks = [
        stock("US", "A.US", classification=dict(sector="Technology", industry="Semiconductors")),
        stock("US", "B.US"),
        stock("US", "C.US", classification=dict(sector="Financial Services", industry="Shell Companies")),
        stock("US", "D.US", "DELISTED", dict(sector="Technology", industry="Semiconductors")),
        stock("CN", "600000.SH"),
        stock("HK", "5.HK"),
    ]
    memberships = [
        dict(stock_code="600000.SH", industry_code="881155.TI"),
        dict(stock_code="600000.SH", industry_code="884249.TI"),
        dict(stock_code="600000.SH", industry_code="881157.TI"),
    ]
    report = summarize(stocks, memberships, {"SMH.US", "512800.SH", "512880.SH"})
    assert report["groups"]["US:ACTIVE"] == dict(
        total=3, classified=2, covered=1, multiple_proxies=0, coverage_pct=33.33, classified_coverage_pct=50.0
    )
    assert report["groups"]["US:DELISTED"]["covered"] == 1
    assert report["groups"]["CN:ACTIVE"]["covered"] == 1
    assert report["groups"]["CN:ACTIVE"]["multiple_proxies"] == 1
    assert report["groups"]["HK:ACTIVE"]["classified"] == 0
    # 映射存在但ETF已从实际轮动池移除，不再计入覆盖。
    assert summarize(stocks, memberships, set())["groups"]["US:ACTIVE"]["covered"] == 0
    with pytest.raises(ValueError, match="Duplicate"):
        summarize([stocks[0], stocks[0]])


def test_unreviewed_classification_is_reported_without_sector_fallback():
    stocks = [
        dict(
            market="US",
            code="A.US",
            listing_status="ACTIVE",
            metadata={"classification": dict(sector="Technology", industry="New industry")},
        )
    ]
    report = summarize(stocks)
    assert report["unreviewed"] == [("US", "('Technology', 'New industry')")]
    assert report["groups"]["US:ACTIVE"]["covered"] == 0


def test_operating_industries_have_proxies_and_approximate_matches_explain_the_gap():
    assert {key for key, value in US_INDUSTRY_ETF.items() if value.etf_code is None} == {
        ("Financial Services", "Shell Companies")
    }
    assert {key for key, value in CN_INDUSTRY_ETF.items() if value.etf_code is None} == {"881165.TI"}
    assert "近似替代" in resolve_industry_etf("CN", "881112.TI").reason
    assert "不是钢铁" in resolve_industry_etf("CN", "881112.TI").reason
