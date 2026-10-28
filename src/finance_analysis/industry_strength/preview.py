"""Current-session previews in dedicated latest-only database tables."""

from datetime import time, timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.core.preview_storage import json_ready
from finance_analysis.database.repositories.research_preview import PreviewRepository
from finance_analysis.market_review.trading_calendar import get_market_now, is_market_open

from .service import IndustryReadinessError, IndustryStrengthService

TTL = 86400


class PreviewCache:
    def __init__(self, repository=None):
        self.repository = repository or PreviewRepository()

    def write(self, payload, *, started_at=None):
        ready = json_ready(payload)
        result = ready.get("result")
        items, groups = [], {}
        if result is not None:
            result = dict(result)
            for row in result.pop("items", []):
                items.append({"kind": "industry", "item_key": row["industry_code"], "summary": row})
            for code, members in result.pop("constituents", {}).items():
                groups[code] = {key: value for key, value in members.items() if key != "items"}
                for row in members.get("items", []):
                    items.append({"kind": f"members:{code}", "item_key": row["code"], "summary": row})
            ready["result"] = result
        stamp = utc_now()
        self.repository.publish(
            "industry_strength", "CN", 0,
            {"payload": ready, "member_groups": groups, "trade_date": (result or {}).get("trade_date")}, items,
            observed_at=started_at or stamp, expires_at=stamp + timedelta(seconds=TTL),
        )

    @staticmethod
    def _payload(stored, *, members=True):
        if not stored:
            return None
        payload = stored["header"]["payload"]
        result = payload.get("result")
        if result is None:
            return payload
        groups = stored["header"]["member_groups"]
        constituents = {code: {**info, "items": [
            row["summary"] for row in stored["items"] if row["kind"] == f"members:{code}"
        ]} for code, info in groups.items()} if members else {}
        return {**payload, "result": {**result, "constituents": constituents,
                "items": [row["summary"] for row in stored["items"] if row["kind"] == "industry"]}}

    def read(self):
        return self._payload(self.repository.read("industry_strength", "CN"))

    def read_view(self, field):
        if field == "ranking":
            return self._payload(self.repository.read("industry_strength", "CN", kind="industry"), members=False)
        if not field.startswith("members:"):
            return None
        stored = self.repository.read("industry_strength", "CN", kind=field)
        code = field.removeprefix("members:")
        if not stored or code not in stored["header"]["member_groups"]:
            return None
        result = stored["header"]["payload"]["result"]
        return {"generated_at": result["generated_at"], "trade_date": result["trade_date"], "constituents": {
            **stored["header"]["member_groups"][code], "items": [row["summary"] for row in stored["items"]],
        }}


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
        started_at = utc_now()
        self.cache.write({"status": "processing", "error": None, "result": None}, started_at=started_at)
        try:
            payload = self.build_preview()
            self.cache.write({"status": "completed", "error": None, "result": payload}, started_at=started_at)
            return {"status": "completed", "trade_date": payload["trade_date"].isoformat()}
        except Exception as exc:
            self.cache.write({"status": "failed", "error": str(exc), "failed_at": utc_now(), "result": None},
                             started_at=started_at)
            raise

    def build_preview(self):
        day = current_day()
        rows, constituents, stamps = self.calculate(day, False, preview=True)
        now = utc_now()
        trend_date = self.repository.latest_cn_trend_date()
        grouped, member_items = {}, {}
        for member in constituents:
            member_items.setdefault(member["industry_code"], []).append({
                "code": member["stock_code"], "name": member["stock_name"],
                **{k: v for k, v in member.items() if k not in {"industry_code", "stock_code", "stock_name"}},
            })
        for row in rows:
            row.update(created_at=now, updated_at=now)
            row["quality"].pop("member_codes", None)
            row["quality"].update(breadth_basis="intraday_weekly_observed_members", turnover_basis="intraday_cumulative")
            code = row["industry_code"]
            grouped[code] = {
                "industry_code": code,
                "updated_at": now,
                "trend_rank_date": trend_date,
                "items": member_items.get(code, []),
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
