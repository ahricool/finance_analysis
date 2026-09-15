# -*- coding: utf-8 -*-
"""
大盘复盘市场区域配置

定义各市场区域的指数、Prompt 提示等元数据，
供 MarketAnalyzer 按 region 切换 A 股/美股复盘行为。
"""

from dataclasses import dataclass


@dataclass
class MarketProfile:
    """大盘复盘市场区域配置"""

    region: str  # "cn" | "us"
    # 用于判断整体走势的指数代码，cn 用上证 000001，us 用标普 SPX
    mood_index_code: str
    # 指数点评 Prompt 提示语
    prompt_index_hint: str
    # 市场概况是否包含涨跌家数、涨停跌停（A 股有，美股无）
    has_market_stats: bool
    # 市场概况是否包含板块涨跌（A 股有，美股暂无）
    has_sector_rankings: bool


CN_PROFILE = MarketProfile(
    region="cn",
    mood_index_code="000001",
    prompt_index_hint="分析上证、深证、创业板等各指数走势特点",
    has_market_stats=True,
    has_sector_rankings=True,
)

US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    prompt_index_hint="分析标普500、纳斯达克、道指等各指数走势特点",
    has_market_stats=False,
    has_sector_rankings=False,
)

HK_PROFILE = MarketProfile(
    region="hk",
    mood_index_code="HSI",
    prompt_index_hint="分析恒生指数、恒生科技指数、国企指数等各指数走势特点",
    has_market_stats=False,
    has_sector_rankings=False,
)


def get_profile(region: str) -> MarketProfile:
    """根据 region 返回对应的 MarketProfile"""
    if region == "us":
        return US_PROFILE
    if region == "hk":
        return HK_PROFILE
    return CN_PROFILE
