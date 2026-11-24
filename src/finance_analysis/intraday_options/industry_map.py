"""Reference data for the intraday options industry tree, independent of live quotes."""

import logging
import math

from redis.exceptions import RedisError

from finance_analysis.database.repositories.intraday_simulation import load_universe_symbols
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.intraday_options.config import BENCHMARK_SYMBOL_SET
from finance_analysis.market_heatmap.cache import HeatmapCache
from finance_analysis.market_heatmap.config import US_SECTOR_NAMES

logger = logging.getLogger(__name__)


def read_industry_map_metadata():
    symbols = tuple(symbol for symbol in load_universe_symbols() if symbol not in BENCHMARK_SYMBOL_SET)
    instruments = InstrumentRepository().get_by_codes(symbols)
    try:
        heatmap = HeatmapCache().read("US") or {}
    except (RedisError, ValueError):
        logger.warning("美股市值缓存暂不可用，继续展示日内行业分类", exc_info=True)
        heatmap = {}

    caps = {}
    for row in heatmap.get("items", ()):
        cap = row.get("market_cap")
        if isinstance(cap, (int, float)) and math.isfinite(cap) and cap > 0:
            caps[row["code"]] = cap

    items = []
    for symbol in symbols:
        instrument = instruments.get(symbol)
        metadata = instrument.instrument_metadata if instrument else None
        classification = (metadata or {}).get("classification") or {}
        sector = classification.get("sector")
        items.append({
            "symbol": symbol,
            "sector": US_SECTOR_NAMES.get(sector, sector),
            "industry": classification.get("industry"),
            "market_cap": caps.get(symbol),
        })
    return {"market_cap_as_of": heatmap.get("generated_at"), "items": items}
