# -*- coding: utf-8 -*-
"""US intraday anomaly detection service.

This task is alert-oriented: it keeps short-lived intraday bars in Redis,
computes rule-based candidates, and asks the LLM to decide whether the signal
is worth surfacing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

from data_provider.longbridge_fetcher import LongbridgeFetcher
from data_provider.realtime_types import UnifiedRealtimeQuote, safe_float
from data_provider.yfinance_fetcher import YfinanceFetcher

logger = logging.getLogger(__name__)

US_EASTERN = ZoneInfo("America/New_York")
REDIS_TTL_SECONDS = 7 * 24 * 60 * 60
SIGNAL_DEDUP_TTL_SECONDS = 30 * 60
MARKET_ETFS = ("QQQ", "SOXX", "UFO")


DEFAULT_INTRADAY_SIGNAL_RULES: Dict[str, Dict[str, float]] = {
    "relative_strength_breakout": {
        "change_5m_min": 0.8,
        "change_15m_min": 1.5,
        "relative_to_qqq_15m_min": 0.8,
        "volume_ratio_5m_min": 2.0,
        "near_high_pct": 0.25,
    },
    "weak_to_strong_reversal": {
        "early_relative_to_qqq_max": -0.3,
        "relative_to_qqq_15m_min": 0.3,
        "change_15m_min": 1.0,
        "volume_ratio_5m_min": 1.8,
    },
    "relative_strength_failure": {
        "early_relative_to_qqq_min": 0.5,
        "relative_to_qqq_15m_max": -0.3,
        "change_5m_max": -0.8,
        "volume_ratio_5m_min": 2.0,
    },
}


@dataclass
class IntradaySignalResult:
    symbol: str
    signal_type: str
    need_notification: bool
    llm_result: Dict[str, Any]
    metrics: Dict[str, Any]
    calendar_id: Optional[int] = None
    notification_sent: bool = False


@dataclass
class IntradayTaskSummary:
    market_open: bool
    total_symbols: int = 0
    processed_symbols: int = 0
    skipped_symbols: int = 0
    candidate_count: int = 0
    signal_results: List[IntradaySignalResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def is_us_market_open(now: Optional[datetime] = None) -> bool:
    """Return whether now is within regular US market hours."""
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    current = current.astimezone(US_EASTERN)

    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar("XNYS")
        return bool(calendar.is_open_on_minute(current, ignore_breaks=True))
    except Exception as exc:
        logger.debug("exchange_calendars unavailable for US market-open check: %s", exc)

    if current.weekday() >= 5:
        return False
    return time(9, 30) <= current.time() < time(16, 0)


def get_us_trading_date(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    return current.astimezone(US_EASTERN).date().isoformat()


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    return dt.astimezone(US_EASTERN)


def _normalize_bar(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ts = _parse_timestamp(raw.get("timestamp"))
    close = safe_float(raw.get("close"))
    open_price = safe_float(raw.get("open"))
    high = safe_float(raw.get("high"))
    low = safe_float(raw.get("low"))
    if ts is None or close is None or open_price is None or high is None or low is None:
        return None
    volume = int(raw.get("volume") or 0)
    turnover = safe_float(raw.get("turnover"))
    return {
        "timestamp": ts.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "turnover": turnover,
    }


def normalize_bars(raw_bars: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bars = [_normalize_bar(bar) for bar in raw_bars]
    return sorted((bar for bar in bars if bar is not None), key=lambda item: item["timestamp"])


def aggregate_bars(bars: Sequence[Dict[str, Any]], interval_minutes: int) -> List[Dict[str, Any]]:
    """Aggregate normalized 1-minute bars into N-minute bars."""
    if interval_minutes <= 1:
        return list(bars)

    grouped: Dict[datetime, List[Dict[str, Any]]] = {}
    for bar in bars:
        ts = _parse_timestamp(bar.get("timestamp"))
        if ts is None:
            continue
        bucket_minute = (ts.minute // interval_minutes) * interval_minutes
        bucket = ts.replace(minute=bucket_minute, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(bar)

    aggregated: List[Dict[str, Any]] = []
    for bucket in sorted(grouped):
        items = sorted(grouped[bucket], key=lambda item: item["timestamp"])
        turnover_values = [safe_float(item.get("turnover")) for item in items]
        turnover = (
            sum(v for v in turnover_values if v is not None)
            if any(v is not None for v in turnover_values)
            else None
        )
        aggregated.append(
            {
                "timestamp": bucket.isoformat(),
                "open": items[0]["open"],
                "high": max(item["high"] for item in items),
                "low": min(item["low"] for item in items),
                "close": items[-1]["close"],
                "volume": sum(int(item.get("volume") or 0) for item in items),
                "turnover": turnover,
            }
        )
    return aggregated


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100, 4)


def _change_over_minutes(bars: Sequence[Dict[str, Any]], minutes: int) -> Optional[float]:
    if len(bars) < 2:
        return None
    latest_ts = _parse_timestamp(bars[-1].get("timestamp"))
    if latest_ts is None:
        return None
    cutoff = latest_ts - timedelta(minutes=minutes)
    baseline = None
    for bar in reversed(bars[:-1]):
        ts = _parse_timestamp(bar.get("timestamp"))
        if ts is not None and ts <= cutoff:
            baseline = safe_float(bar.get("close"))
            break
    if baseline is None:
        baseline = safe_float(bars[0].get("open"))
    return _pct_change(safe_float(bars[-1].get("close")), baseline)


def _volume_ratio_5m(bars_5m: Sequence[Dict[str, Any]], lookback: int = 12) -> Optional[float]:
    if len(bars_5m) < 3:
        return None
    current_volume = int(bars_5m[-1].get("volume") or 0)
    previous = [
        int(bar.get("volume") or 0)
        for bar in bars_5m[-lookback - 1:-1]
        if int(bar.get("volume") or 0) > 0
    ]
    if not previous:
        return None
    avg_volume = sum(previous) / len(previous)
    if avg_volume <= 0:
        return None
    return round(current_volume / avg_volume, 4)


def _vwap(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    total_volume = 0
    total_value = 0.0
    for bar in bars:
        volume = int(bar.get("volume") or 0)
        if volume <= 0:
            continue
        turnover = safe_float(bar.get("turnover"))
        if turnover is not None and turnover > 0:
            value = turnover
        else:
            typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3
            value = typical * volume
        total_volume += volume
        total_value += value
    if total_volume <= 0:
        return None
    return round(total_value / total_volume, 4)


def _first_hour_change(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    if len(bars) < 2:
        return None
    first_ts = _parse_timestamp(bars[0].get("timestamp"))
    if first_ts is None:
        return None
    end = first_ts + timedelta(minutes=60)
    last_in_window = None
    for bar in bars:
        ts = _parse_timestamp(bar.get("timestamp"))
        if ts is not None and ts <= end:
            last_in_window = bar
    if last_in_window is None:
        return None
    return _pct_change(safe_float(last_in_window.get("close")), safe_float(bars[0].get("open")))


def _crossed_above_vwap(bars: Sequence[Dict[str, Any]], vwap_value: Optional[float]) -> bool:
    if vwap_value is None or len(bars) < 2:
        return False
    previous = safe_float(bars[-2].get("close"))
    current = safe_float(bars[-1].get("close"))
    return bool(previous is not None and current is not None and previous < vwap_value <= current)


def _crossed_below_vwap(bars: Sequence[Dict[str, Any]], vwap_value: Optional[float]) -> bool:
    if vwap_value is None or len(bars) < 2:
        return False
    previous = safe_float(bars[-2].get("close"))
    current = safe_float(bars[-1].get("close"))
    return bool(previous is not None and current is not None and previous > vwap_value >= current)


def compute_intraday_metrics(
    symbol: str,
    bars_1m: Sequence[Dict[str, Any]],
    quote: Optional[UnifiedRealtimeQuote],
    benchmark_metrics: Optional[Dict[str, Any]] = None,
    sector_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    bars_5m = aggregate_bars(bars_1m, 5)
    bars_15m = aggregate_bars(bars_1m, 15)
    latest_price = safe_float(getattr(quote, "price", None)) if quote is not None else None
    if latest_price is None and bars_1m:
        latest_price = safe_float(bars_1m[-1].get("close"))

    vwap_value = _vwap(bars_1m)
    intraday_high = max((float(bar["high"]) for bar in bars_1m), default=None)
    intraday_low = min((float(bar["low"]) for bar in bars_1m), default=None)
    high_distance_pct = None
    if latest_price is not None and intraday_high and intraday_high > 0:
        high_distance_pct = round((intraday_high - latest_price) / intraday_high * 100, 4)

    change_5m = _change_over_minutes(bars_1m, 5)
    change_15m = _change_over_minutes(bars_1m, 15)
    change_60m = _change_over_minutes(bars_1m, 60)
    first_hour = _first_hour_change(bars_1m)

    benchmark_metrics = benchmark_metrics or {}
    qqq_change_15m = safe_float(benchmark_metrics.get("change_15m"))
    qqq_first_hour = safe_float(benchmark_metrics.get("first_hour_change"))

    relative_to_qqq_15m = None
    if change_15m is not None and qqq_change_15m is not None:
        relative_to_qqq_15m = round(change_15m - qqq_change_15m, 4)

    early_relative_to_qqq = None
    if first_hour is not None and qqq_first_hour is not None:
        early_relative_to_qqq = round(first_hour - qqq_first_hour, 4)

    relative_to_sector_15m: Dict[str, Optional[float]] = {}
    for sector_symbol, metrics in (sector_metrics or {}).items():
        sector_change = safe_float(metrics.get("change_15m"))
        relative_to_sector_15m[sector_symbol] = (
            round(change_15m - sector_change, 4) if change_15m is not None and sector_change is not None else None
        )

    price_above_vwap = bool(latest_price is not None and vwap_value is not None and latest_price > vwap_value)
    price_below_vwap = bool(latest_price is not None and vwap_value is not None and latest_price < vwap_value)

    return {
        "symbol": symbol,
        "price": latest_price,
        "change_5m": change_5m,
        "change_15m": change_15m,
        "change_60m": change_60m,
        "first_hour_change": first_hour,
        "volume_ratio_5m": _volume_ratio_5m(bars_5m),
        "vwap": vwap_value,
        "price_above_vwap": price_above_vwap,
        "price_below_vwap": price_below_vwap,
        "crossed_above_vwap": _crossed_above_vwap(bars_1m, vwap_value),
        "crossed_below_vwap": _crossed_below_vwap(bars_1m, vwap_value),
        "intraday_high": intraday_high,
        "intraday_low": intraday_low,
        "near_intraday_high": bool(high_distance_pct is not None and high_distance_pct <= 0.25),
        "high_distance_pct": high_distance_pct,
        "relative_to_qqq_15m": relative_to_qqq_15m,
        "early_relative_to_qqq": early_relative_to_qqq,
        "relative_to_sector_15m": relative_to_sector_15m,
        "bars_count_1m": len(bars_1m),
        "bars_count_5m": len(bars_5m),
        "bars_count_15m": len(bars_15m),
        "latest_bar_time": bars_1m[-1]["timestamp"] if bars_1m else None,
        "quote": _quote_to_dict(quote),
    }


def evaluate_signal_candidates(
    metrics: Dict[str, Any],
    rules: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate decoupled threshold rules and return candidate signal types."""
    cfg = rules or DEFAULT_INTRADAY_SIGNAL_RULES
    candidates: List[Dict[str, Any]] = []

    breakout = cfg["relative_strength_breakout"]
    if (
        _gte(metrics.get("change_5m"), breakout["change_5m_min"])
        and _gte(metrics.get("change_15m"), breakout["change_15m_min"])
        and _gte(metrics.get("relative_to_qqq_15m"), breakout["relative_to_qqq_15m_min"])
        and _gte(metrics.get("volume_ratio_5m"), breakout["volume_ratio_5m_min"])
        and metrics.get("price_above_vwap")
        and (
            metrics.get("near_intraday_high")
            or _lte(metrics.get("high_distance_pct"), breakout["near_high_pct"])
        )
    ):
        candidates.append({"signal_type": "relative_strength_breakout", "rule": breakout})

    reversal = cfg["weak_to_strong_reversal"]
    if (
        _lte(metrics.get("early_relative_to_qqq"), reversal["early_relative_to_qqq_max"])
        and _gte(metrics.get("relative_to_qqq_15m"), reversal["relative_to_qqq_15m_min"])
        and metrics.get("crossed_above_vwap")
        and _gte(metrics.get("change_15m"), reversal["change_15m_min"])
        and _gte(metrics.get("volume_ratio_5m"), reversal["volume_ratio_5m_min"])
    ):
        candidates.append({"signal_type": "weak_to_strong_reversal", "rule": reversal})

    failure = cfg["relative_strength_failure"]
    if (
        _gte(metrics.get("early_relative_to_qqq"), failure["early_relative_to_qqq_min"])
        and _lte(metrics.get("relative_to_qqq_15m"), failure["relative_to_qqq_15m_max"])
        and metrics.get("price_below_vwap")
        and _lte(metrics.get("change_5m"), failure["change_5m_max"])
        and _gte(metrics.get("volume_ratio_5m"), failure["volume_ratio_5m_min"])
    ):
        candidates.append({"signal_type": "relative_strength_failure", "rule": failure})

    return candidates


def _gte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed >= threshold)


def _lte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed <= threshold)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _quote_to_dict(quote: Optional[UnifiedRealtimeQuote]) -> Dict[str, Any]:
    if quote is None:
        return {}
    return {
        "price": safe_float(getattr(quote, "price", None)),
        "change_pct": safe_float(getattr(quote, "change_pct", None)),
        "volume": int(getattr(quote, "volume", 0) or 0),
        "open_price": safe_float(getattr(quote, "open_price", None)),
        "high": safe_float(getattr(quote, "high", None)),
        "low": safe_float(getattr(quote, "low", None)),
        "pre_close": safe_float(getattr(quote, "pre_close", None)),
        "source": getattr(getattr(quote, "source", None), "value", str(getattr(quote, "source", ""))),
    }


def build_intraday_llm_prompt(
    symbol: str,
    signal_type: str,
    metrics: Dict[str, Any],
    raw_context: Dict[str, Any],
) -> str:
    payload = {
        "symbol": symbol,
        "signal_type": signal_type,
        "metrics": metrics,
        "raw_context": raw_context,
    }
    return (
        "你是美股盘中异动提醒系统的分析员。请基于输入的实时行情、1分钟K线聚合指标、"
        "相对 QQQ/SOXX/UFO 的强弱关系，判断这个信号是否真的值得关注。\n\n"
        "重点回答：\n"
        "1. 这个信号是真突破/反转/失效，还是普通波动？\n"
        "2. 是个股自身强，还是被 QQQ、SOXX、UFO 等板块/大盘带动？\n"
        "3. 当前追高或追空风险大不大？\n"
        "4. 是否值得发通知？\n\n"
        "只输出一个 JSON object，不要 markdown，不要解释 JSON 之外的文字。格式如下：\n"
        "{\n"
        '  "final_decision": "watch|ignore|risk",\n'
        '  "need_notification": true,\n'
        '  "confidence": 0.76,\n'
        '  "summary": "一句话摘要",\n'
        '  "reason": "为什么这不是普通波动/或者为什么只是普通波动",\n'
        '  "risk": "追高/失效/回落风险",\n'
        '  "suggestion": "观察或处理建议"\n'
        "}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_llm_json_response(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            snippet = stripped[start:end + 1]
        else:
            snippet = stripped
        try:
            from json_repair import repair_json

            parsed = json.loads(repair_json(snippet))
        except Exception:
            return None
    return parsed if isinstance(parsed, dict) else None


class USIntradayAnalysisService:
    def __init__(
        self,
        *,
        config: Any,
        redis_client: Optional[Any] = None,
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        yfinance_fetcher: Optional[YfinanceFetcher] = None,
        rules: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        self.config = config
        self.redis = redis_client if redis_client is not None else self._create_redis_client(config)
        self.longbridge = longbridge_fetcher or LongbridgeFetcher()
        self.yfinance = yfinance_fetcher or YfinanceFetcher()
        self.rules = rules or DEFAULT_INTRADAY_SIGNAL_RULES

    def run(self, stock_codes: Sequence[str], now: Optional[datetime] = None) -> IntradayTaskSummary:
        if not is_us_market_open(now):
            return IntradayTaskSummary(market_open=False, total_symbols=len(stock_codes))

        summary = IntradayTaskSummary(market_open=True, total_symbols=len(stock_codes))
        trade_date = get_us_trading_date(now)
        market_context = self._load_market_context(trade_date)
        qqq_metrics = market_context.get("QQQ", {})
        sector_metrics = {k: v for k, v in market_context.items() if k != "QQQ"}

        for raw_code in stock_codes:
            symbol = self._normalize_us_symbol(raw_code)
            try:
                bars_1m = self._fetch_1m_bars(symbol)
                if len(bars_1m) < 20:
                    summary.skipped_symbols += 1
                    logger.info("美股盘中分析跳过 %s: 1m K线不足(%s)", symbol, len(bars_1m))
                    continue

                quote = self._fetch_quote(symbol)
                self._cache_bars(symbol, trade_date, bars_1m)
                metrics = compute_intraday_metrics(symbol, bars_1m, quote, qqq_metrics, sector_metrics)
                self._cache_latest(symbol, metrics, trade_date)

                candidates = evaluate_signal_candidates(metrics, self.rules)
                summary.processed_symbols += 1
                summary.candidate_count += len(candidates)
                for candidate in candidates:
                    signal_type = candidate["signal_type"]
                    if not self._reserve_signal(symbol, signal_type):
                        logger.info("美股盘中信号去重跳过: %s %s", symbol, signal_type)
                        continue
                    result = self._analyze_candidate(symbol, signal_type, metrics, bars_1m, market_context)
                    if result:
                        summary.signal_results.append(result)
            except Exception as exc:
                logger.exception("美股盘中分析 %s 失败: %s", raw_code, exc)
                summary.errors.append(f"{raw_code}: {exc}")

        return summary

    @staticmethod
    def _create_redis_client(config: Any) -> Optional[Any]:
        try:
            import redis

            return redis.Redis.from_url(getattr(config, "redis_url", "redis://localhost:6379/0"), decode_responses=True)
        except Exception as exc:
            logger.warning("Redis 初始化失败，美股盘中缓存/去重将降级: %s", exc)
            return None

    @staticmethod
    def _normalize_us_symbol(code: str) -> str:
        symbol = (code or "").strip().upper()
        if symbol.endswith(".US"):
            return symbol[:-3]
        return symbol

    def _fetch_1m_bars(self, symbol: str) -> List[Dict[str, Any]]:
        bars = normalize_bars(self.longbridge.get_minute_candlesticks(symbol, interval=1, count=520))
        if bars:
            return bars
        logger.info("Longbridge 1m K线为空，使用 yfinance 兜底: %s", symbol)
        return self._fetch_yfinance_1m_bars(symbol)

    @staticmethod
    def _fetch_yfinance_1m_bars(symbol: str) -> List[Dict[str, Any]]:
        try:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(period="1d", interval="1m", prepost=False, auto_adjust=False)
            if hist.empty:
                return []
            raw_bars: List[Dict[str, Any]] = []
            for ts, row in hist.iterrows():
                turnover = None
                close = safe_float(row.get("Close"))
                volume = int(row.get("Volume") or 0)
                if close is not None and volume > 0:
                    turnover = close * volume
                raw_bars.append(
                    {
                        "timestamp": ts.isoformat(),
                        "open": safe_float(row.get("Open")),
                        "high": safe_float(row.get("High")),
                        "low": safe_float(row.get("Low")),
                        "close": close,
                        "volume": volume,
                        "turnover": turnover,
                    }
                )
            return normalize_bars(raw_bars)
        except Exception as exc:
            logger.info("yfinance 1m K线兜底失败 %s: %s", symbol, exc)
            return []

    def _fetch_quote(self, symbol: str) -> Optional[UnifiedRealtimeQuote]:
        quote = self.longbridge.get_realtime_quote(symbol)
        if quote is not None:
            return quote
        return self.yfinance.get_realtime_quote(symbol)

    def _load_market_context(self, trade_date: str) -> Dict[str, Dict[str, Any]]:
        context: Dict[str, Dict[str, Any]] = {}
        for symbol in MARKET_ETFS:
            cached = self._redis_get_json(f"intraday:latest:US:{symbol}")
            if cached and cached.get("trade_date") == trade_date:
                context[symbol] = cached
                continue
            bars_1m = self._fetch_1m_bars(symbol)
            if len(bars_1m) < 10:
                continue
            quote = self._fetch_quote(symbol)
            self._cache_bars(symbol, trade_date, bars_1m)
            metrics = compute_intraday_metrics(symbol, bars_1m, quote)
            self._cache_latest(symbol, metrics, trade_date)
            context[symbol] = metrics
        return context

    def _cache_bars(self, symbol: str, trade_date: str, bars_1m: Sequence[Dict[str, Any]]) -> None:
        if self.redis is None:
            return
        for interval, bars in (
            (1, list(bars_1m)),
            (5, aggregate_bars(bars_1m, 5)),
            (15, aggregate_bars(bars_1m, 15)),
        ):
            self._redis_set_json(
                f"intraday:bars:US:{symbol}:{trade_date}:{interval}m",
                bars,
                ex=REDIS_TTL_SECONDS,
            )

    def _cache_latest(self, symbol: str, metrics: Dict[str, Any], trade_date: str) -> None:
        payload = {
            **metrics,
            "trade_date": trade_date,
            "cached_at": datetime.now(US_EASTERN).isoformat(),
        }
        self._redis_set_json(f"intraday:latest:US:{symbol}", payload, ex=REDIS_TTL_SECONDS)

    def _reserve_signal(self, symbol: str, signal_type: str) -> bool:
        if self.redis is None:
            return True
        key = f"intraday:dedup:US:{symbol}:{signal_type}"
        try:
            return bool(self.redis.set(key, "1", ex=SIGNAL_DEDUP_TTL_SECONDS, nx=True))
        except Exception as exc:
            logger.warning("Redis 信号去重失败，允许继续: %s", exc)
            return True

    def _analyze_candidate(
        self,
        symbol: str,
        signal_type: str,
        metrics: Dict[str, Any],
        bars_1m: Sequence[Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
    ) -> Optional[IntradaySignalResult]:
        llm_result = self._call_llm(symbol, signal_type, metrics, bars_1m, market_context)
        if llm_result is None:
            return None

        need_notification = _truthy(llm_result.get("need_notification"))
        final_decision = str(llm_result.get("final_decision") or "").lower()
        if final_decision not in {"watch", "risk"}:
            need_notification = False

        signal = IntradaySignalResult(
            symbol=symbol,
            signal_type=signal_type,
            need_notification=need_notification,
            llm_result=llm_result,
            metrics=metrics,
        )
        signal.calendar_id = self._record_signal_to_calendar(signal)
        if need_notification:
            signal.notification_sent = self._send_notification(signal)
        return signal

    def _call_llm(
        self,
        symbol: str,
        signal_type: str,
        metrics: Dict[str, Any],
        bars_1m: Sequence[Dict[str, Any]],
        market_context: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        try:
            from src.analyzer import GeminiAnalyzer

            analyzer = GeminiAnalyzer(self.config)
            if not analyzer.is_available():
                logger.warning("LLM 未配置，跳过美股盘中候选信号判定: %s %s", symbol, signal_type)
                return None
            prompt = build_intraday_llm_prompt(
                symbol,
                signal_type,
                metrics,
                {
                    "bars_1m_tail": list(bars_1m[-30:]),
                    "bars_5m_tail": aggregate_bars(bars_1m, 5)[-12:],
                    "bars_15m_tail": aggregate_bars(bars_1m, 15)[-8:],
                    "market_context": market_context,
                },
            )
            text = analyzer.generate_text(prompt, max_tokens=1200, temperature=0.2)
            parsed = parse_llm_json_response(text)
            if parsed is None:
                logger.warning("美股盘中 LLM 返回无法解析: %s %s", symbol, signal_type)
                return None
            return parsed
        except Exception as exc:
            logger.warning("美股盘中 LLM 调用失败 %s %s: %s", symbol, signal_type, exc)
            return None

    def _record_signal_to_calendar(self, signal: IntradaySignalResult) -> Optional[int]:
        try:
            from src.repositories.calendar_repo import CalendarRepo
            from src.repositories.user_repo import UserRepository

            uid = UserRepository().ensure_default_admin()
            now = datetime.now(US_EASTERN)
            title = f"美股盘中异动：{signal.symbol} {signal.signal_type}"
            content = self._render_calendar_content(signal)
            entry = CalendarRepo().create(
                uid=uid,
                time=now,
                title=title[:120],
                content=content,
                type="us_intraday_signal",
            )
            return int(getattr(entry, "id", 0) or 0)
        except Exception as exc:
            logger.warning("写入美股盘中信号日历失败: %s", exc)
            return None

    @staticmethod
    def _render_calendar_content(signal: IntradaySignalResult) -> str:
        result = signal.llm_result
        metrics = signal.metrics
        lines = [
            f"## {signal.symbol} 盘中异动",
            "",
            f"- 信号类型：{signal.signal_type}",
            f"- 最终决策：{result.get('final_decision', '-')}",
            f"- 是否通知：{bool(result.get('need_notification'))}",
            f"- 置信度：{result.get('confidence', '-')}",
            f"- 价格：{metrics.get('price', '-')}",
            f"- 5分钟涨跌幅：{metrics.get('change_5m', '-')}%",
            f"- 15分钟涨跌幅：{metrics.get('change_15m', '-')}%",
            f"- 相对 QQQ 15分钟强弱：{metrics.get('relative_to_qqq_15m', '-')}%",
            f"- 5分钟量比：{metrics.get('volume_ratio_5m', '-')}",
            f"- VWAP：{metrics.get('vwap', '-')}",
            "",
            "### LLM 判断",
            "",
            f"- 摘要：{result.get('summary', '-')}",
            f"- 理由：{result.get('reason', '-')}",
            f"- 风险：{result.get('risk', '-')}",
            f"- 建议：{result.get('suggestion', '-')}",
            "",
            "### 指标 JSON",
            "",
            f"```json\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n```",
        ]
        return "\n".join(lines)

    def _send_notification(self, signal: IntradaySignalResult) -> bool:
        try:
            from src.notification import NotificationService

            content = self._render_notification(signal)
            return NotificationService().send(
                content,
                email_stock_codes=[signal.symbol],
                route_type="alert",
                severity="warning",
                dedup_key=f"us_intraday:{signal.symbol}:{signal.signal_type}",
                cooldown_key=f"us_intraday:{signal.symbol}",
            )
        except Exception as exc:
            logger.warning("发送美股盘中信号通知失败: %s", exc)
            return False

    @staticmethod
    def _render_notification(signal: IntradaySignalResult) -> str:
        result = signal.llm_result
        metrics = signal.metrics
        return "\n".join(
            [
                f"**美股盘中异动：{signal.symbol}**",
                "",
                f"- 信号：{signal.signal_type}",
                f"- 决策：{result.get('final_decision', '-')}",
                f"- 置信度：{result.get('confidence', '-')}",
                f"- 摘要：{result.get('summary', '-')}",
                f"- 理由：{result.get('reason', '-')}",
                f"- 风险：{result.get('risk', '-')}",
                f"- 建议：{result.get('suggestion', '-')}",
                "",
                (
                    f"价格 {metrics.get('price', '-')} | 5m {metrics.get('change_5m', '-')}% | "
                    f"15m {metrics.get('change_15m', '-')}% | "
                    f"相对 QQQ {metrics.get('relative_to_qqq_15m', '-')}% | "
                    f"量比 {metrics.get('volume_ratio_5m', '-')}"
                ),
            ]
        )

    def _redis_get_json(self, key: str) -> Optional[Dict[str, Any]]:
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(key)
            if not raw:
                return None
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            logger.debug("Redis get json failed %s: %s", key, exc)
            return None

    def _redis_set_json(self, key: str, value: Any, *, ex: int) -> None:
        if self.redis is None:
            return
        try:
            self.redis.set(key, json.dumps(value, ensure_ascii=False), ex=ex)
        except Exception as exc:
            logger.debug("Redis set json failed %s: %s", key, exc)
