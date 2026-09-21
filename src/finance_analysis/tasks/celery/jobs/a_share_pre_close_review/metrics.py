"""Deterministic market, sector, and security calculations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional, Sequence

import pandas as pd

from finance_analysis.integrations.market_data.codes import is_etf_code, normalize_stock_code  # pragma: allowlist secret
from finance_analysis.integrations.market_data.realtime_types import safe_float  # pragma: allowlist secret
from finance_analysis.market_review.price_limits import (  # pragma: allowlist secret
    _limit_ratio_for,
    _structural_board,
    is_risk_warning,
)
from .models import SectorReview


def parse_snapshot_time(rows: Sequence[dict[str, Any]]) -> Optional[datetime]:
    quote_values = [row.get("quote_time") for row in rows[:200] if row.get("quote_time")]
    parsed_quote_times = [parsed for value in quote_values if (parsed := _parse_datetime(value)) is not None]
    if parsed_quote_times:
        return max(parsed_quote_times)
    values = [row.get("snapshot_time") for row in rows[:20] if row.get("snapshot_time")]
    for value in values:
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.astimezone()
    except (TypeError, ValueError):
        return None


def index_change_map(indices: Sequence[dict[str, Any]]) -> dict[str, float]:
    changes: dict[str, float] = {}
    for item in indices:
        code = normalize_stock_code(str(item.get("code") or ""))
        value = safe_float(item.get("change_pct"))
        if code and value is not None:
            changes[code] = value
    return changes


def determine_market_state(
    breadth: dict[str, Any],
    indices: Sequence[dict[str, Any]],
) -> tuple[str, str, list[str]]:
    changes = list(index_change_map(indices).values())
    average_index = sum(changes) / len(changes) if changes else None
    up_ratio = safe_float(breadth.get("up_ratio"))
    limit_down = int(breadth.get("limit_down_count") or 0)
    break_rate = safe_float(breadth.get("break_rate"))

    rationale: list[str] = []
    if average_index is not None:
        rationale.append(f"主要指数平均涨跌幅 {average_index:+.2f}%")
    if up_ratio is not None:
        rationale.append(f"上涨家数占比 {up_ratio:.1%}")
    rationale.append(f"涨停/跌停 {int(breadth.get('limit_up_count') or 0)}/{limit_down} 家")
    if break_rate is not None:
        rationale.append(f"炸板率 {break_rate:.1%}")

    if not changes or up_ratio is None:
        return "unknown", "unknown", rationale
    if average_index >= 0.6 and up_ratio >= 0.58 and limit_down <= 8:
        return "risk_on", "low", rationale
    if average_index <= -0.8 or up_ratio <= 0.32 or limit_down >= 25:
        return "risk_off", "high", rationale
    if (break_rate or 0) >= 0.45 or (average_index > 0 and up_ratio < 0.42):
        return "divergent", "elevated", rationale
    return "balanced", "medium", rationale


def determine_turnover_state(
    current_amount: float,
    previous_results: Sequence[dict[str, Any]],
) -> str:
    previous = [
        safe_float((item.get("breadth") or {}).get("total_amount"))
        for item in previous_results
        if isinstance(item, dict)
    ]
    comparable = sorted(value for value in previous if value and value > 0)
    if current_amount <= 0:
        return "unknown"
    if not comparable:
        return "unconfirmed"
    median = comparable[len(comparable) // 2]
    ratio = current_amount / median if median else 1.0
    if ratio >= 1.12:
        return "expanded"
    if ratio <= 0.88:
        return "contracted"
    return "normal"


def review_strong_sectors(
    sectors: Sequence[dict[str, Any]],
    previous_results: Sequence[dict[str, Any]],
    *,
    market_state: str,
    limit: int,
) -> list[SectorReview]:
    prior_names: list[str] = []
    for result in previous_results:
        for item in result.get("strong_sectors", []) if isinstance(result, dict) else []:
            name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
            if name:
                prior_names.append(name)

    reviews: list[SectorReview] = []
    for raw in sectors[:limit]:
        name = str(raw.get("name") or "").strip()
        change = safe_float(raw.get("change_pct"))
        if not name or change is None:
            continue
        high = safe_float(raw.get("high"))
        price = safe_float(raw.get("price"))
        open_price = safe_float(raw.get("open"))
        pullback = ((high - price) / high * 100) if high and price and high > 0 else None
        appearances = prior_names.count(name)

        if pullback is not None and pullback >= 1.2:
            continuity = "surge_fade"
            reason = "当前价格较日内高点明显回落"
        elif appearances >= 1 and (pullback is None or pullback <= 0.6):
            continuity = "trend"
            reason = f"近 {len(previous_results)} 次结果中出现 {appearances} 次且仍接近日内高位"
        elif appearances >= 1 and market_state in {"divergent", "risk_off"}:
            continuity = "high_divergence"
            reason = "近期持续强势，但市场宽度或风险状态出现分歧"
        elif change >= 2.5 and open_price and price and price >= open_price:
            continuity = "breakout"
            reason = "涨幅居前且未出现明显冲高回落"
        elif change >= 2.5:
            continuity = "one_day_pulse"
            reason = "当日涨幅较高，但缺少历史延续记录"
        else:
            continuity = "uncertain"
            reason = "板块居前但趋势确认信息有限"
        reviews.append(
            SectorReview(
                name=name,
                change_pct=round(change, 3),
                continuity=continuity,
                rationale=reason,
                pullback_from_high_pct=round(pullback, 3) if pullback is not None else None,
                prior_appearances=appearances,
            )
        )
    return reviews


def daily_trend(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty or "close" not in frame.columns:
        return "insufficient"
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna().tail(20)
    if len(closes) < 10:
        return "insufficient"
    last = float(closes.iloc[-1])
    ma5 = float(closes.tail(5).mean())
    ma20 = float(closes.mean())
    ten_day_return = (last / float(closes.iloc[-10]) - 1) * 100
    if last > ma5 > ma20 and ten_day_return >= 1:
        return "uptrend"
    if last < ma5 < ma20 and ten_day_return <= -1:
        return "downtrend"
    return "sideways"


def intraday_trend(bars: Sequence[dict[str, Any]], *, minimum_bars: int) -> str:
    closes = [safe_float(item.get("close")) for item in bars]
    values = [value for value in closes if value and value > 0]
    if len(values) < minimum_bars:
        return "insufficient"
    change = (values[-1] / values[0] - 1) * 100
    recent = sum(values[-5:]) / min(5, len(values))
    earlier = sum(values[:5]) / min(5, len(values))
    if change >= 0.8 and recent > earlier:
        return "strengthening"
    if change <= -0.8 and recent < earlier:
        return "weakening"
    return "range"


def unrealized_pct(price: Optional[float], avg_cost: Optional[float]) -> Optional[float]:
    if price is None or avg_cost is None or price <= 0 or avg_cost <= 0:
        return None
    return round((price / avg_cost - 1) * 100, 3)

def compute_market_breadth(rows: Sequence[dict[str, Any]], trading_date: date) -> dict[str, Any]:
    """Deterministic A-share market breadth from a snapshot. Used by pre-close review."""
    del trading_date
    up = down = flat = 0
    limit_up = limit_down = 0
    touched_up = opened_up = 0
    touched_down = 0
    up5 = down5 = 0
    high_open_low = 0
    total_amount = 0.0
    counted = 0

    for row in rows:
        code = normalize_stock_code(str(row.get("code") or ""))
        name = str(row.get("name") or "")
        if not code or is_etf_code(code):
            continue
        price = safe_float(row.get("price"))
        pre_close = safe_float(row.get("pre_close"))
        amount = safe_float(row.get("amount"))
        change_pct = safe_float(row.get("change_pct"))
        if amount is not None:
            total_amount += amount
        if price is None or pre_close is None or price <= 0 or pre_close <= 0:
            continue
        counted += 1
        if price > pre_close:
            up += 1
        elif price < pre_close:
            down += 1
        else:
            flat += 1
        if change_pct is not None:
            if change_pct >= 5:
                up5 += 1
            elif change_pct <= -5:
                down5 += 1
        ratio = _limit_ratio_for(_structural_board(code), is_risk_warning(name))
        if ratio is None:
            continue
        limit_up_price = round(pre_close * (1 + ratio), 2)
        limit_down_price = round(pre_close * (1 - ratio), 2)
        high = safe_float(row.get("high"))
        low = safe_float(row.get("low"))
        open_price = safe_float(row.get("open"))
        is_lu = abs(price - limit_up_price) / limit_up_price * 100 <= 0.05
        is_ld = abs(price - limit_down_price) / limit_down_price * 100 <= 0.05
        if is_lu:
            limit_up += 1
        if is_ld:
            limit_down += 1
        if high is not None and high >= limit_up_price - 0.005:
            touched_up += 1
            if not is_lu:
                opened_up += 1
        if low is not None and low <= limit_down_price + 0.005:
            touched_down += 1
        if open_price is not None and open_price > pre_close * 1.015 and price < open_price * 0.99:
            high_open_low += 1

    break_rate = (opened_up / touched_up) if touched_up > 0 else None
    return {
        "counted_symbols": counted,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "touched_limit_up_count": touched_up,
        "opened_from_limit_up_count": opened_up,
        "touched_limit_down_count": touched_down,
        "up_over_5_count": up5,
        "down_over_5_count": down5,
        "high_open_low_count": high_open_low,
        "break_rate": break_rate,
        "total_amount": round(total_amount / 1e8, 4) if total_amount else 0.0,
        "up_ratio": round(up / counted, 4) if counted else None,
        "down_ratio": round(down / counted, 4) if counted else None,
    }
