"""Current-session previews, atomically published in Redis; never save official rows."""

import json
from datetime import time

from finance_analysis.core.time import utc_now
from finance_analysis.etf_rotation.preview_cache import _redis_client, json_ready
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open

from .service import IndustryReadinessError, IndustryStrengthService

KEY = "industry_strength:preview:v1"
TTL = 86400


class PreviewCache:
    def __init__(self, client=None):
        self.client = client if client is not None else _redis_client()

    def read(self, key=KEY):
        raw = self.client.get(key)
        return json.loads(raw) if raw else None

    def write(self, payload, key=KEY):
        self.client.set(key, json.dumps(json_ready(payload), ensure_ascii=False), ex=TTL)


def current_day():
    now = get_market_now("cn")
    if not is_market_open("cn", now.date()) or now.time() < time(9, 30):
        raise IndustryReadinessError("盘中预览仅支持当前交易日开盘后")
    return now.date()


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
        rows, constituents, stamps = self.calculate(day, False, preview=True)
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
            raise IndustryReadinessError("预览采集跨越交易日，等待下一次定时任务")
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
