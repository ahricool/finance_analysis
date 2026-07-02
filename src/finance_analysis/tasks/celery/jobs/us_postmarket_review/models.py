# -*- coding: utf-8 -*-
"""Domain models for the scheduled US post-market review task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

US_POSTMARKET_BENCHMARKS = {
    "SPY": "标普500",
    "QQQ": "纳斯达克100",
    "DIA": "道琼斯",
    "IWM": "罗素2000",
}

US_POSTMARKET_SECTOR_ETFS = {
    "XLK": "科技",
    "SOXX": "半导体",
    "XLF": "金融",
    "XLE": "能源",
    "XLY": "可选消费",
    "XLP": "必选消费",
    "XLV": "医疗",
    "XLI": "工业",
    "XLU": "公用事业",
    "XLB": "原材料",
    "XLRE": "房地产",
}

US_POSTMARKET_TASK_TYPE = "scheduled_us_postmarket_review"
US_POSTMARKET_TIMEZONE = "America/New_York"


@dataclass
class InstrumentPerformance:
    """Normalized daily OHLCV performance used by the report context."""

    symbol: str
    name: str
    close: float
    change_pct: float
    volume: int = 0
    volume_ratio: Optional[float] = None
    relative_to_spy: Optional[float] = None
    relative_to_qqq: Optional[float] = None
    source: str = ""

    def to_context_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "close": round(self.close, 4),
            "change_pct": round(self.change_pct, 4),
            "volume": self.volume,
            "volume_ratio": round(self.volume_ratio, 4) if self.volume_ratio is not None else None,
            "relative_to_spy": round(self.relative_to_spy, 4) if self.relative_to_spy is not None else None,
            "relative_to_qqq": round(self.relative_to_qqq, 4) if self.relative_to_qqq is not None else None,
            "source": self.source,
        }


@dataclass
class WatchlistSummary:
    total_count: int = 0
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    average_change_pct: float = 0.0
    gainers: List[InstrumentPerformance] = field(default_factory=list)
    losers: List[InstrumentPerformance] = field(default_factory=list)
    outperform_qqq: List[InstrumentPerformance] = field(default_factory=list)
    underperform_qqq: List[InstrumentPerformance] = field(default_factory=list)
    unusual_volume: List[InstrumentPerformance] = field(default_factory=list)

    def to_context_dict(self) -> Dict[str, Any]:
        return {
            "total_count": self.total_count,
            "up_count": self.up_count,
            "down_count": self.down_count,
            "flat_count": self.flat_count,
            "average_change_pct": round(self.average_change_pct, 4),
        }


@dataclass
class USPostmarketReviewContext:
    trading_date: date
    benchmarks: List[InstrumentPerformance]
    sector_etfs: List[InstrumentPerformance]
    sector_top3: List[InstrumentPerformance]
    sector_bottom3: List[InstrumentPerformance]
    style_bias: str
    market_regime: str
    watchlist_summary: WatchlistSummary
    news: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)

    def to_llm_payload(self) -> Dict[str, Any]:
        return {
            "trading_date": self.trading_date.isoformat(),
            "benchmarks": [item.to_context_dict() for item in self.benchmarks],
            "sector_etfs": [item.to_context_dict() for item in self.sector_etfs],
            "sector_top3": [item.to_context_dict() for item in self.sector_top3],
            "sector_bottom3": [item.to_context_dict() for item in self.sector_bottom3],
            "style_bias": self.style_bias,
            "market_regime": self.market_regime,
            "watchlist_summary": self.watchlist_summary.to_context_dict(),
            "watchlist_gainers": [
                item.to_context_dict() for item in self.watchlist_summary.gainers[:5]
            ],
            "watchlist_losers": [
                item.to_context_dict() for item in self.watchlist_summary.losers[:5]
            ],
            "watchlist_outperform_qqq": [
                item.to_context_dict() for item in self.watchlist_summary.outperform_qqq[:8]
            ],
            "watchlist_underperform_qqq": [
                item.to_context_dict() for item in self.watchlist_summary.underperform_qqq[:8]
            ],
            "unusual_volume_symbols": [
                item.to_context_dict() for item in self.watchlist_summary.unusual_volume[:8]
            ],
            "news": self.news[:15],
            "warnings": self.warnings[:30],
        }


@dataclass
class USPostmarketReviewSummary:
    trading_date: date
    started_at: datetime
    finished_at: datetime
    benchmark_count: int = 0
    sector_count: int = 0
    watchlist_count: int = 0
    watchlist_up_count: int = 0
    watchlist_down_count: int = 0
    market_regime: str = "neutral"
    report: str = ""
    report_file: Optional[str] = None
    calendar_id: Optional[int] = None
    notification_sent: bool = False
    fallback_used: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trading_date": self.trading_date.isoformat(),
            "market_regime": self.market_regime,
            "benchmark_count": self.benchmark_count,
            "sector_count": self.sector_count,
            "watchlist_count": self.watchlist_count,
            "watchlist_up_count": self.watchlist_up_count,
            "watchlist_down_count": self.watchlist_down_count,
            "calendar_id": self.calendar_id,
            "notification_sent": self.notification_sent,
            "fallback_used": self.fallback_used,
            "warnings": list(self.warnings),
        }
