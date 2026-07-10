"""Bounded historical and intraday analysis for holdings and finalists."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from finance_analysis.integrations.market_data.codes import normalize_stock_code
from finance_analysis.integrations.market_data.realtime_types import safe_float

from .config import MARKET_TREND_PROXIES, PreCloseReviewConfig
from .data_source import ASharePreCloseDataSource
from .metrics import daily_trend, intraday_trend, unrealized_pct
from .models import DataQuality, SecurityReview


class PreCloseSecurityAnalyzer:
    """Analyzes only current holdings and the deterministic finalist pool."""

    def __init__(
        self,
        *,
        data_source: ASharePreCloseDataSource,
        limits: PreCloseReviewConfig,
        quality: DataQuality,
        now: datetime,
        benchmark_change: Optional[float],
    ) -> None:
        self.data_source = data_source
        self.limits = limits
        self.quality = quality
        self.now = now
        self.benchmark_change = benchmark_change
        self.board_lookups = 0

    def load_market_trends(self) -> list[dict[str, Any]]:
        trends = []
        for code, name in MARKET_TREND_PROXIES.items():
            frame, source = self.data_source.get_daily_history(code, days=self.limits.history_days)
            trend = daily_trend(frame)
            if trend == "insufficient":
                self.quality.issues.append(f"{name} 近期趋势数据不足")
            trends.append({"code": code, "name": name, "trend": trend, "source": source})
        return trends

    def review_holdings(
        self,
        holdings: Sequence[Any],
        quote_by_code: dict[str, dict[str, Any]],
        sector_changes: dict[str, float],
    ) -> list[SecurityReview]:
        reviews = []
        for holding in holdings:
            code = normalize_stock_code(str(self._field(holding, "code") or ""))
            quote = quote_by_code.get(code, {})
            if quote:
                self.quality.holding_coverage += 1
            reviews.append(
                self._review_security(
                    code=code,
                    name=str(self._field(holding, "name") or quote.get("name") or code),
                    quote=quote,
                    sector_changes=sector_changes,
                    source="holding",
                    avg_cost=safe_float(self._field(holding, "avg_cost")),
                )
            )
        return reviews

    def review_candidates(
        self,
        rows: Sequence[dict[str, Any]],
        strong_sector_changes: dict[str, float],
    ) -> list[SecurityReview]:
        reviews: list[SecurityReview] = []
        for quote in rows:
            code = normalize_stock_code(str(quote.get("code") or ""))
            sector = self._matched_sector(code, strong_sector_changes, require_strong=True)
            if sector is None:
                continue
            review = self._review_security(
                code=code,
                name=str(quote.get("name") or code),
                quote=quote,
                sector_changes=strong_sector_changes,
                source="candidate",
                sector=sector,
            )
            if review.data_complete and review.daily_trend != "downtrend" and review.intraday_trend != "weakening":
                reviews.append(review)
            if len(reviews) >= self.limits.max_candidates:
                break
        return reviews

    def _review_security(
        self,
        *,
        code: str,
        name: str,
        quote: dict[str, Any],
        sector_changes: dict[str, float],
        source: str,
        avg_cost: Optional[float] = None,
        sector: Optional[str] = None,
    ) -> SecurityReview:
        if sector is None:
            sector = self._matched_sector(code, sector_changes)
        frame, _ = self.data_source.get_daily_history(code, days=self.limits.history_days)
        trend = daily_trend(frame)
        if trend != "insufficient":
            self.quality.history_coverage += 1
        elif source == "holding":
            self.quality.issues.append(f"持仓 {code} 日线数据不足")

        bars = self.data_source.get_minute_bars(code, count=self.limits.minute_bar_count, now=self.now)
        intraday = intraday_trend(bars, minimum_bars=self.limits.minimum_minute_bars)
        if intraday != "insufficient":
            self.quality.minute_coverage += 1
        elif source == "holding":
            self.quality.issues.append(f"持仓 {code} 分钟K线不足")

        change = safe_float(quote.get("change_pct"))
        price = safe_float(quote.get("price"))
        sector_change = sector_changes.get(sector) if sector else None
        data_complete = bool(
            self.quality.fresh_quotes
            and quote
            and change is not None
            and price is not None
            and trend != "insufficient"
            and intraday != "insufficient"
        )
        return SecurityReview(
            code=code,
            name=name,
            change_pct=round(change, 3) if change is not None else None,
            price=price,
            amount=safe_float(quote.get("amount")),
            sector=sector,
            relative_to_market_pct=(
                round(change - self.benchmark_change, 3)
                if change is not None and self.benchmark_change is not None
                else None
            ),
            relative_to_sector_pct=(
                round(change - sector_change, 3) if change is not None and sector_change is not None else None
            ),
            daily_trend=trend,
            intraday_trend=intraday,
            data_complete=data_complete,
            avg_cost=avg_cost,
            unrealized_pct=unrealized_pct(price, avg_cost),
            source=source,
        )

    def _matched_sector(
        self,
        code: str,
        sector_changes: dict[str, float],
        *,
        require_strong: bool = False,
    ) -> Optional[str]:
        if self.board_lookups >= self.limits.max_board_lookups:
            return None
        self.board_lookups += 1
        boards = self.data_source.get_belonging_boards(code)
        for sector_name in sector_changes:
            if any(sector_name == board or sector_name in board or board in sector_name for board in boards):
                return sector_name
        return None if require_strong or not boards else boards[0]

    @staticmethod
    def _field(item: Any, name: str) -> Any:
        return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


__all__ = ["PreCloseSecurityAnalyzer"]
