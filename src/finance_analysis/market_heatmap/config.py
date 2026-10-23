"""Display universe and refresh policy; capitalization is in the market's currency."""

MIN_MARKET_CAP = {"CN": 10_000_000_000, "US": 2_000_000_000}
REFRESH_SECONDS = 15 * 60
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

US_SECTOR_NAMES = {
    "Basic Materials": "基础材料",
    "Communication Services": "通信服务",
    "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必需消费",
    "Energy": "能源",
    "Financial Services": "金融服务",
    "Healthcare": "医疗健康",
    "Industrials": "工业",
    "Real Estate": "房地产",
    "Technology": "科技",
    "Utilities": "公用事业",
}
