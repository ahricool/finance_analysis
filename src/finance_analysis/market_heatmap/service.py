"""Stock-only market views, built in workers and served from Redis."""

import math

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data.service import MarketDataService

from .cache import HeatmapCache
from .config import MIN_MARKET_CAP, REFRESH_SECONDS, US_SECTOR_NAMES


class HeatmapService:
    def __init__(self, market_data=None, instruments=None, industries=None, cache=None):
        self.market_data = market_data
        self.instruments = instruments
        self.industries = industries
        self.cache = cache or HeatmapCache()

    def refresh(self, market):
        if market not in MIN_MARKET_CAP:
            raise ValueError("Unsupported heatmap market")
        provider = "easyquotation" if market == "CN" else "yfinance"
        data = (self.market_data or MarketDataService()).get_market_snapshot(
            market,
            providers=[provider],
            min_market_cap=MIN_MARKET_CAP[market],
        )
        if not data.data or market in data.failed_symbols:
            raise ValueError("Market snapshot unavailable; previous heatmap retained")
        instruments = (self.instruments or InstrumentRepository()).get_by_codes(data.data)
        groups, observations = {}, []
        if market == "CN":
            catalog, memberships = (self.industries or IndustryStrengthRepository()).reference_data()
            if not catalog:
                raise ValueError("Industry reference unavailable; run weekly industry reference sync")
            # The source has overlapping broad/sub-industry indexes, but no parent links.
            # Prefer the broadest observed membership, then code, so each stock is counted once.
            for industry in sorted(catalog, key=lambda r: (-len(memberships[r["thscode"]]), r["thscode"])):
                for member in memberships[industry["thscode"]]:
                    groups.setdefault(member["thscode"], (industry["thscode"], industry["name"]))
            observations = [row["members_observed_at"].isoformat() for row in catalog]
        rows, excluded = [], 0
        for code, quote in data.data.items():
            instrument = instruments.get(code)
            if instrument is None or instrument.instrument_type != "STOCK" or instrument.listing_status != "ACTIVE":
                excluded += 1
                continue
            cap = quote.total_mv
            if (
                cap is None
                or not math.isfinite(cap)
                or cap < MIN_MARKET_CAP[market]
                or quote.currency != instrument.currency
            ):
                excluded += 1
                continue
            if market == "US":
                classification = (instrument.instrument_metadata or {}).get("classification", {})
                sector = classification.get("sector")
                group = (sector, US_SECTOR_NAMES.get(sector, sector)) if sector else ("unknown", "未分类")
                if classification.get("observed_at"):
                    observations.append(classification["observed_at"])
            else:
                group = groups.get(code, ("unknown", "未分类"))
            change = quote.change_pct
            if change is not None and not math.isfinite(change):
                change = None
            rows.append(
                {
                    "code": code,
                    "name": quote.name or instrument.name,
                    "market_cap": cap,
                    "price": quote.price,
                    "change_pct": change,
                    "group_code": group[0],
                    "group_name": group[1],
                    "quote_time": quote.quote_time.isoformat() if quote.quote_time else None,
                }
            )
        if not rows:
            raise ValueError("No eligible stocks; previous heatmap retained")
        previous = self.cache.read(market)
        if previous and len(rows) < len(previous["items"]) * 0.8:
            raise ValueError("Heatmap coverage dropped; previous generation retained")
        stamps = [row["quote_time"] for row in rows if row["quote_time"]]
        payload = {
            "market": market,
            "source": provider,
            "generated_at": utc_now().isoformat(),
            "data_as_of": min(stamps) if stamps else None,
            "data_latest_at": max(stamps) if stamps else None,
            "classification_observed_at": min(observations) if observations else None,
            "min_market_cap": MIN_MARKET_CAP[market],
            "refresh_seconds": REFRESH_SECONDS,
            "excluded_count": excluded,
            "unclassified_count": sum(r["group_code"] == "unknown" for r in rows),
            "items": sorted(rows, key=lambda r: (-r["market_cap"], r["code"])),
        }
        self.cache.write(market, payload)
        return {"market": market, "stock_count": len(rows), "generated_at": payload["generated_at"]}
