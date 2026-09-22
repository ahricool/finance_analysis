"""Current-session previews, atomically published in Redis; never save official rows."""

import json
import math
from datetime import date, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from finance_analysis.core.time import utc_now
from finance_analysis.etf_rotation.preview_cache import _redis_client, json_ready
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open

from .service import IndustryReadinessError, IndustryStrengthService

KEY = "industry_strength:preview:v1"
TTL = 86400
SHANGHAI = ZoneInfo("Asia/Shanghai")


class PreviewCache:
    def __init__(self, client=None):
        self.client = client if client is not None else _redis_client()

    def read(self, key=KEY):
        raw = self.client.get(key)
        return json.loads(raw) if raw else None

    def write(self, payload, key=KEY):
        self.client.set(key, json.dumps(json_ready(payload), ensure_ascii=False), ex=TTL)

    def cached(self, day, name, loader):
        key = f"{KEY}:inputs:{day}:{name}"
        value = self.read(key)
        if value is None:
            value = json_ready(loader())
            self.write(value, key)
        return value


def current_day():
    now = get_market_now("cn")
    if not is_market_open("cn", now.date()) or now.time() < time(9, 30):
        raise IndustryReadinessError("盘中预览仅支持当前交易日开盘后")
    return now.date()


def current_quote(quote, day):
    if quote is None or quote.quote_time is None or quote.quote_time.tzinfo is None:
        return False
    local = quote.quote_time.astimezone(SHANGHAI)
    return (
        local.date() == day
        and local.time() >= time(9, 30)
        and quote.price is not None
        and math.isfinite(quote.price)
        and quote.price > 0
    )


def bar_record(bar):
    return {"trade_date": bar.trade_date, "close": bar.close, "volume": bar.volume, "amount": bar.amount}


def decode_bars(records):
    return [SimpleNamespace(**{**r, "trade_date": date.fromisoformat(r["trade_date"])}) for r in records]


def overlay(bars, quote, day, previous_day, *, stock=False):
    """Replace today's bar. Rebase old forward-adjusted closes to today's ex-rights basis."""
    prior = [bar for bar in bars if bar.trade_date < day]
    if not current_quote(quote, day):
        return prior
    if stock:
        previous = next((b.close for b in prior if b.trade_date == previous_day), None)
        if previous and quote.pre_close and quote.pre_close > 0:
            factor = quote.pre_close / previous
            prior = [SimpleNamespace(**{**bar_record(b), "close": b.close * factor}) for b in prior]
        else:
            # Live daily return remains usable, but MA windows require a known adjustment anchor.
            prior = []
            if quote.pre_close and quote.pre_close > 0:
                prior = [SimpleNamespace(trade_date=previous_day, close=quote.pre_close, volume=None, amount=None)]
    return prior + [SimpleNamespace(trade_date=day, close=quote.price, volume=quote.volume, amount=quote.amount)]


class PreviewInputs:
    def __init__(self, catalog, indices, members, quotes):
        self.catalog, self.indices, self.members, self.quotes = catalog, indices, members, quotes

    def get_industry_catalog(self):
        return self.catalog

    def get_index_history(self, code, start, end):
        return self.indices.get(code, []), self.quotes[code].quote_time if code in self.quotes else None

    def get_index_constituents(self, code):
        return self.members.get(code, [])


class IndustryPreviewService(IndustryStrengthService):
    def __init__(self, *args, cache=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache = cache or PreviewCache()

    def run_preview(self):
        previous = self.cache.read() or {}
        self.cache.write({**previous, "status": "processing", "error": None})
        try:
            payload = self.build_preview()
            self.cache.write({"status": "completed", "error": None, "result": payload})
            return {"status": "completed", "trade_date": payload["trade_date"].isoformat()}
        except Exception as exc:
            self.cache.write({**previous, "status": "failed", "error": str(exc), "failed_at": utc_now()})
            raise

    def build_preview(self):
        day = current_day()
        sessions = self.sessions(day)
        cache, data = self.cache, self.market_data
        catalog = cache.cached(day, "catalog", data.get_industry_catalog)
        indices, members = {}, {}
        for code in [self.config.benchmark] + [r["thscode"] for r in catalog]:
            try:
                records = cache.cached(
                    day,
                    f"index:{code}",
                    lambda: [bar_record(b) for b in data.get_index_history(code, sessions[0], sessions[-2])[0]],
                )
                indices[code] = decode_bars(records)
            except (ValueError, RuntimeError):
                indices[code] = []
            if code != self.config.benchmark:
                try:
                    members[code] = cache.cached(day, f"members:{code}", lambda: data.get_index_constituents(code))
                except (ValueError, RuntimeError):
                    members[code] = []
        codes = sorted({m["thscode"] for rows in members.values() for m in rows})
        records = (
            cache.cached(
                day,
                "stocks",
                lambda: {
                    code: [bar_record(b) for b in bars]
                    for code, bars in self.load_member_history(codes, sessions[:-1]).items()
                },
            )
            if codes
            else {}
        )
        index_quotes = data.get_index_quotes(list(indices))
        stock_quotes = data.get_realtime_quotes(codes).data if codes else {}
        indices = {code: overlay(bars, index_quotes.get(code), day, sessions[-2]) for code, bars in indices.items()}
        stocks = {
            code: overlay(decode_bars(records.get(code, [])), stock_quotes.get(code), day, sessions[-2], stock=True)
            for code in codes
        }
        calculator = IndustryStrengthService(
            self.repository, PreviewInputs(catalog, indices, members, index_quotes), self.config
        )
        rows, constituents = calculator.calculate(day, False, persist=False, member_histories=stocks)
        now = utc_now()
        trend_date = self.repository.latest_cn_trend_date()
        grouped = {}
        for row in rows:
            row.update(created_at=now, updated_at=now)
            row["quality"].pop("member_codes", None)
            row["quality"].update(breadth_basis="intraday_current_members", turnover_basis="intraday_cumulative")
            code = row["industry_code"]
            items = [
                {
                    "code": r["stock_code"],
                    "name": r["stock_name"],
                    **{k: v for k, v in r.items() if k not in {"industry_code", "stock_code", "stock_name"}},
                }
                for r in constituents
                if r["industry_code"] == code
            ]
            grouped[code] = {
                "industry_code": code,
                "updated_at": now,
                "trend_rank_date": trend_date,
                "items": items,
                **{
                    k: row[k]
                    for k in (
                        "constituent_count",
                        "daily_valid_count",
                        "ma5_valid_count",
                        "above_ma5_count",
                        "ma20_valid_count",
                        "above_ma20_count",
                    )
                },
            }
        if current_day() != day:
            raise IndustryReadinessError("预览采集跨越交易日，请重新刷新")
        stamps = [q.quote_time for q in [*index_quotes.values(), *stock_quotes.values()] if current_quote(q, day)]
        return {
            "trade_date": day,
            "expected_trade_date": day,
            "source": "盘中行情 / 扶摇行业指数",
            "generated_at": now,
            "data_as_of": min(stamps),
            "data_latest_at": max(stamps),
            "items": rows,
            "constituents": grouped,
        }
