"""Small, timestamped LLM inputs. Raw research detail and all-market rows never enter prompts."""

from datetime import datetime, timedelta, timezone
import math

from finance_analysis.core.time import coerce_aware_utc, utc_isoformat
from finance_analysis.core.preview_storage import merge_dict
from finance_analysis.database.repositories.research_preview import PreviewRepository
from finance_analysis.database.repositories.stock import InstrumentRepository
from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.market_review.trading_calendar import get_market_now
from finance_analysis.portfolio.resolver import PortfolioResolver
from .calendar import default_dates

INDICES = {
    "CN": {"000001.SH": "上证指数", "399006.SZ": "创业板指", "000300.SH": "沪深300"},
    "US": {"SPX.US": "标普500指数", "NDX.US": "纳斯达克100指数", "DJI.US": "道琼斯指数"},
}
QUOTE_MAX_AGE = 180
PREVIEW_MAX_AGE = 20 * 60
DAILY_COUNT = 20
MINUTE_COUNT = 12


def number(value):
    try:
        result = float(value)
        return round(result, 6) if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def stamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return coerce_aware_utc(result) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def pick(row, fields):
    return {key: row[key] for key in fields if row.get(key) is not None}


def candle(bar, key):
    values = [number(getattr(bar, name, None)) for name in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in values):
        return None
    opening, high, low, close = values
    if high < max(opening, close, low) or low > min(opening, close, high):
        return None
    return [key, *values, number(getattr(bar, "volume", None))]


def daily_rows(bars, day):
    rows = {}
    for bar in bars:
        if bar.trade_date < day:
            value = candle(bar, bar.trade_date.isoformat())
            if value:
                rows[value[0]] = value
    return [rows[key] for key in sorted(rows)][-DAILY_COUNT:]


def minute_rows(bars, market, now):
    """Closed native 1m bars aggregated into five-minute windows, last 12 only."""
    groups = {}
    for bar in bars:
        when = stamp(getattr(bar, "bar_time", None))
        if not when or get_market_now(market.lower(), when).date() != now.date():
            continue
        local_time = get_market_now(market.lower(), when)
        opening = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if when < opening or (market == "CN" and (11, 30) <= (local_time.hour, local_time.minute) < (13, 0)):
            continue
        if when + timedelta(minutes=1) > now:
            continue
        row = candle(bar, utc_isoformat(when))
        if row:
            bucket = int(when.timestamp()) // 300 * 300
            groups.setdefault(bucket, {})[when] = row
    result = []
    for bucket, values in sorted(groups.items()):
        ordered = [values[key] for key in sorted(values)]
        # Do not pretend an unfinished 5m window is a completed candle.
        if len(ordered) != 5 or datetime.fromtimestamp(bucket + 300, timezone.utc) > now:
            continue
        volumes = [r[5] for r in ordered]
        result.append(
            [
                utc_isoformat(datetime.fromtimestamp(bucket, timezone.utc)),
                ordered[0][1],
                max(r[2] for r in ordered),
                min(r[3] for r in ordered),
                ordered[-1][4],
                sum(volumes) if all(v is not None for v in volumes) else None,
            ]
        )
    return result[-MINUTE_COUNT:]


class ReviewContextBuilder:
    def __init__(self, *, market_data=None, resolver=None, previews=None, instruments=None):
        self.data = market_data or MarketDataService()
        self.resolver = resolver or PortfolioResolver()
        self.previews = previews or PreviewRepository()
        self.instruments = instruments or InstrumentRepository()

    def _preview(self, namespace, market, now, *, keys=None, limit=5, variant=0):
        if namespace == "industry_strength" and market != "CN":
            return {"status": "unsupported", "reason": "行业强度仅覆盖 A 股", "items": []}
        try:
            stored = self.previews.read(
                namespace,
                market,
                variant,
                kind="industry" if namespace == "industry_strength" else "stock",
                item_keys=keys,
                limit=limit,
                view="summary",
                now=now,
            )
            if not stored:
                return {"status": "missing", "items": []}
            header = stored["header"]
            payload = header.get("payload", header)
            if namespace == "industry_strength":
                if payload.get("status") != "completed":
                    return {"status": "unavailable", "items": []}
                payload = payload.get("result") or {}
            if payload.get("status") not in {None, "completed"}:
                return {"status": "unavailable", "items": []}
            observed = stamp(payload.get("preview_time") or payload.get("generated_at") or stored.get("observed_at"))
            observed_day = get_market_now(market.lower(), observed).date() if observed else None
            source_time = stamp(payload.get("data_as_of")) or observed
            if (
                not observed
                or observed > now
                or source_time > now
                or observed_day != now.date()
                or str(header.get("trade_date")) != now.date().isoformat()
                or (now - source_time).total_seconds() > PREVIEW_MAX_AGE
            ):
                return {"status": "stale_or_unverified", "observed_at": utc_isoformat(observed), "items": []}
            rows = []
            for item in stored["items"]:
                common = stored["shared"]
                if namespace == "trend_following":
                    common = {**common.get("values", {}), **{k: header.get(k) for k in common.get("header_fields", [])}}
                row = merge_dict(common, item["summary"])
                fields = {
                    "etf_rotation": ("code", "name", "rank", "composite_score", "momentum_score", "is_candidate"),
                    "trend_following": ("code", "state", "alpha_score", "trend_lifecycle", "fragility_score"),
                    "industry_strength": (
                        "industry_code",
                        "industry_name",
                        "state",
                        "strength_score",
                        "strength_rank",
                        "up_ratio",
                        "above_ma20_ratio",
                        "momentum_acceleration_5d",
                    ),
                }[namespace]
                rows.append(pick(row, fields))
            result = {"status": "available", "observed_at": utc_isoformat(observed), "items": rows}
            if keys is not None:
                result["missing_symbols"] = sorted(set(keys) - {row.get("code") for row in rows})
            return result
        except Exception as exc:
            return {"status": "unavailable", "reason": type(exc).__name__, "items": []}

    def build(self, uid, market, now, session_close):
        day = now.date()
        _, expected_history_day = default_dates(market, now)
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        positions = list(portfolio.valuation_positions(market))
        symbols = list(dict.fromkeys(p.symbol for p in positions))
        quality = []
        try:
            names = self.instruments.names_by_codes(symbols)
        except Exception:
            names = {}
        try:
            quotes = self.data.get_realtime_quotes(symbols).data if symbols else {}
        except Exception:
            quotes = {}
            quality.append("持仓实时报价获取失败")
        # Native US index identifiers are explicitly mapped by the market-data facade.
        history_codes = symbols + (list(INDICES[market]) if market == "US" else [])
        try:
            histories = self.data.get_daily_bars(
                history_codes, day - timedelta(days=80), day, adjustment="forward", source_policy="db_latest"
            ).data
        except Exception:
            histories = {}
            quality.append("历史日线获取失败")
        try:
            minutes = (
                self.data.get_minute_bars(
                    symbols,
                    now.replace(hour=9, minute=30, second=0, microsecond=0),
                    now,
                    interval="1m",
                    include_incomplete=False,
                ).data
                if symbols
                else {}
            )
        except Exception:
            minutes = {}
            quality.append("持仓分钟线获取失败")
        research = {
            "etf_rotation": self._preview("etf_rotation", market, now),
            "holding_trends": self._preview("trend_following", market, now, keys=symbols, limit=None, variant=20),
            "industry_strength": self._preview("industry_strength", market, now),
        }
        for key, value in research.items():
            if value["status"] not in {"available", "unsupported"}:
                quality.append(f"{key}：当前有效预演不可用")
        missing_trends = research["holding_trends"].get("missing_symbols", [])
        if missing_trends:
            quality.append("部分持仓不在当日趋势预演覆盖内：" + "、".join(missing_trends[:8]))
        account_names = {a.account_id: a.name for a in getattr(portfolio, "accounts", [])}
        holding_rows = []
        values = []
        for p in positions:
            quote = quotes.get(p.symbol)
            when = stamp(quote.quote_time) if quote else None
            fresh = bool(
                when
                and get_market_now(market.lower(), when).date() == day
                and -30 <= (now - when).total_seconds() <= QUOTE_MAX_AGE
            )
            price = number(quote.price) if quote and fresh else None
            if price is not None and price <= 0:
                price = None
            historical = daily_rows(histories.get(p.symbol, []), day)
            intraday = minute_rows(minutes.get(p.symbol, []), market, now)
            daily_fresh = bool(historical and historical[-1][0] == expected_history_day.isoformat())
            last_minute = stamp(intraday[-1][0]) + timedelta(minutes=5) if intraday else None
            minute_fresh = bool(last_minute and (now - last_minute).total_seconds() <= 360)
            quantity, cost = number(p.quantity), number(p.average_cost)
            value = price * quantity if price is not None else None
            values.append(value)
            if price is None or len(historical) < 10 or not daily_fresh or len(intraday) < 6 or not minute_fresh:
                quality.append(f"{p.symbol}：报价、日线或分钟线覆盖不足，限制主动建议")
            holding_rows.append(
                {
                    "position_id": p.position_id,
                    "account_id": p.account_id,
                    "account_name": account_names.get(p.account_id, f"账户 {p.account_id}"),
                    "symbol": p.symbol,
                    "name": names.get(p.symbol) or p.name or p.symbol,
                    "quantity": quantity,
                    "average_cost": cost,
                    "current_price": price,
                    "quote_time": utc_isoformat(when),
                    "market_value": number(value),
                    "change_pct": number(quote.change_pct) if quote and price is not None else None,
                    "unrealized_pnl_pct": (
                        number((price / cost - 1) * 100) if price is not None and cost and cost > 0 else None
                    ),
                    "today": (
                        {
                            k: number(getattr(quote, field, None))
                            for k, field in (
                                ("open", "open_price"),
                                ("high", "high"),
                                ("low", "low"),
                                ("volume", "volume"),
                                ("amount", "amount"),
                            )
                        }
                        if quote and price is not None
                        else None
                    ),
                    "quote_fresh": price is not None,
                    "daily_bars": historical,
                    "minute_bars": intraday,
                    "data_complete": price is not None
                    and len(historical) >= 10
                    and daily_fresh
                    and len(intraday) >= 6
                    and minute_fresh,
                    "today_buy_quantity": number(
                        sum(
                            lot.quantity
                            for lot in p.lots
                            if get_market_now(market.lower(), lot.entry_time).date() == day
                        )
                    ),
                }
            )
        cash = number(portfolio.db_cash(market))
        complete = all(value is not None for value in values)
        nav = number(cash + sum(value for value in values if value is not None)) if complete else None
        for row in holding_rows:
            row["weight_pct"] = (
                number(row["market_value"] / nav * 100) if nav and row["market_value"] is not None else None
            )
        indices = []
        try:
            index_quotes = {q.symbol: q for q in self.data.get_market_indices(market)}
        except Exception:
            index_quotes = {}
        for symbol, name in INDICES[market].items():
            bars = histories.get(symbol, [])
            if market == "CN":
                try:
                    bars, _ = self.data.get_index_history(symbol, day - timedelta(days=80), day, market="CN")
                except Exception:
                    bars = []
            quote = index_quotes.get(symbol)
            rows = daily_rows(bars, day)
            indices.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "daily_bars": rows,
                    "current_price": number(quote.price) if quote else None,
                    "change_pct": number(quote.change_pct) if quote else None,
                    "quote_time_basis": "fetched_at",
                    "daily_count": len(rows),
                    "today": (
                        {field: number(getattr(quote, field, None)) for field in ("open", "high", "low", "volume")}
                        if quote
                        else None
                    ),
                }
            )
            if not rows:
                quality.append(f"{name}：指数历史 K 线缺失")
        return {
            "market": market,
            "trade_date": day.isoformat(),
            "as_of": utc_isoformat(now),
            "session_close": utc_isoformat(session_close),
            "bar_fields": ["time", "open", "high", "low", "close", "volume"],
            "daily_basis": "前复权历史日线，不含今日未收盘日K；指数为原生点位",
            "minute_basis": "当日闭合1分钟线聚合为5分钟，最近12根；今日成交量为盘中累计",
            "portfolio": {
                "cash": cash,
                "nav": nav,
                "valuation_complete": complete,
                "holding_count": len(positions),
                "currency": "CNY" if market == "CN" else "USD",
            },
            "holdings": holding_rows,
            "indices": indices,
            "research": research,
            "data_quality": quality,
            "constraints": {
                "buy_means_add_to_existing_only": True,
                "no_automatic_execution": True,
                "cn_t_plus_one": market == "CN",
                "do_not_invent_missing_data": True,
            },
        }
