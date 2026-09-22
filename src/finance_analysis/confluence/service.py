"""Aggregate persisted evidence once; GET paths only read the resulting snapshot."""

import logging
from datetime import date, datetime

from finance_analysis.confluence import config as c
from finance_analysis.confluence.engine import aggregate, signal
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.confluence import ConfluenceRepository

logger = logging.getLogger(__name__)
MISSING_ETF = "现有 ETF theme 元数据没有可靠的股票关联键，未进行名称或 LLM 映射"


def json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


class ConfluenceService:
    def __init__(self, repository=None):
        self.repo = repository if repository is not None else ConfluenceRepository()

    def run(self, market, day):
        now = utc_now()
        sources, availability = {}, {}
        for key in ("trend", "quant", "industry", "dragon_tiger"):
            try:
                rows = getattr(self.repo, key)(market, day)
                sources[key] = rows
                availability[key] = dict(
                    status="available" if rows else "unavailable",
                    count=len(rows),
                    trade_date=max((r["trade_date"] for r in rows), default=None),
                )
            except Exception:
                logger.exception("Confluence source %s failed for %s %s", key, market, day)
                sources[key] = []
                availability[key] = dict(
                    status="failed", count=0, trade_date=None, reason="读取正式结果失败；本次未参与评分"
                )
        availability["etf"] = dict(status="unavailable", count=0, trade_date=None, reason=MISSING_ETF)
        if market == "US":
            availability["dragon_tiger"]["reason"] = "US 不适用龙虎榜"
        trend = {r["instrument_id"]: r for r in sources["trend"]}
        quant = {r["instrument_id"]: r for r in sources["quant"]}
        flows = {r["code"]: r for r in sources["dragon_tiger"]}
        industries = {}
        for row in sources["industry"]:
            industries.setdefault(row["code"], []).append(row)
        result = []
        for stock in self.repo.instruments(market):
            member_rows = industries.get(stock["code"], [])
            # Ambiguous memberships are not cherry-picked for the highest score.
            industry = member_rows[0] if len(member_rows) == 1 else None
            facts = {
                "industry": industry,
                "trend": trend.get(stock["id"]),
                "quant": quant.get(stock["id"]),
                "dragon_tiger": flows.get(stock["code"]),
            }
            if not any(facts.values()):
                continue
            signals = {
                key: signal(
                    key,
                    json_safe(value),
                    availability[key].get("reason")
                    or ("行业映射缺失、晚于目标日期或存在多个行业" if key == "industry" else "截至目标日期无正式数据"),
                )
                for key, value in facts.items()
            }
            for key in ("etf",):
                signals[key] = signal(key, unavailable_reason=availability[key]["reason"])
            result.append(
                dict(
                    instrument_id=stock["id"],
                    **aggregate(signals),
                    algorithm_version=c.ALGORITHM_VERSION,
                    generated_at=now,
                )
            )
        published = self.repo.save(
            market,
            day,
            result,
            dict(generated_at=now, algorithm_version=c.ALGORITHM_VERSION, source_availability=json_safe(availability)),
        )
        return dict(
            status="completed" if published else "superseded",
            market=market,
            trade_date=day.isoformat(),
            count=len(result),
            eligible_count=sum(r["eligible"] for r in result),
            source_availability=json_safe(availability),
        )

    def ranking(
        self,
        market,
        day=None,
        min_score=0,
        min_signals=c.MIN_SIGNALS,
        industry=None,
        lifecycle=None,
        early_only=False,
        top_industry=False,
        strong_only=False,
        limit=200,
    ):
        response = self.repo.read(market, day)
        rows = response["items"]

        def industry_top(row):
            rank = row["signals"]["industry"]["evidence"].get("strength_rank")
            return rank is not None and rank <= c.TOP_INDUSTRY

        response["summary"] = dict(
            total=len(rows),
            eligible=sum(r["eligible"] for r in rows),
            strong_confluence=sum(r["strong_confluence"] for r in rows),
            ignition_industry_strong=sum(
                r["eligible"]
                and r["signals"]["industry"]["status"] == "positive"
                and r["signals"]["trend"]["evidence"].get("trend_lifecycle") == "IGNITION"
                for r in rows
            ),
            top_industry_confluence=sum(r["eligible"] and industry_top(r) for r in rows),
        )
        selected = []
        for row in rows:
            industry_facts = row["signals"]["industry"]["evidence"]
            phase = row["signals"]["trend"]["evidence"].get("trend_lifecycle")
            if row["available_signal_count"] < min_signals or row["confluence_score"] is None:
                continue
            if row["confluence_score"] < min_score or (strong_only and not row["strong_confluence"]):
                continue
            if industry and industry not in {industry_facts.get("industry_code"), industry_facts.get("industry_name")}:
                continue
            if lifecycle and lifecycle != phase or early_only and phase not in c.EARLY_LIFECYCLES:
                continue
            if top_industry and not industry_top(row):
                continue
            selected.append(row)
        selected.sort(
            key=lambda row: (
                -row["confluence_score"],
                -row["positive_signal_count"],
                -(row["signals"]["trend"]["score"] or 0),
                -(row["signals"]["industry"]["score"] or 0),
                row["code"],
            )
        )
        response["total"] = len(selected)
        response["items"] = selected[:limit]
        return response
