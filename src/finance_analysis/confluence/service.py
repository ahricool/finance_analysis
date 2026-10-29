"""Aggregate persisted evidence once; GET paths only read the resulting snapshot."""

import logging
from datetime import date, datetime

from finance_analysis.confluence import config as c
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.confluence import ConfluenceRepository

logger = logging.getLogger(__name__)


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
        from time import perf_counter
        from finance_analysis.confluence import v2
        from finance_analysis.confluence.sector_macro import adapt

        started = perf_counter()
        now = utc_now()
        policy = v2.rules()
        sources, availability = {}, {}
        for key in ("classification", *v2.WEIGHTS):
            try:
                getter = getattr(self.repo, "trend_v2" if key == "trend" else key)
                rows = (
                    getter(market, day, classifications=sources["classification"])
                    if key == "etf"
                    else getter(market, day)
                )
                # Stock/ETF/Quant/Options/Sentiment use only the requested formal date.
                if key not in {"macro", "dragon_tiger"}:
                    rows = [r for r in rows if str(r["trade_date"])[:10] == day.isoformat()]
                sources[key] = rows
                availability[key] = dict(
                    status="available" if rows else "unavailable",
                    count=len(rows),
                    trade_date=max((r["trade_date"] for r in rows), default=None),
                )
                if key in {"macro", "sentiment"} and rows:
                    availability[key]["evidence"] = json_safe(rows[0])
            except Exception:
                logger.exception("Confluence source %s failed for %s %s", key, market, day)
                sources[key] = []
                availability[key] = dict(
                    status="failed", count=0, trade_date=None, reason="读取失败；该维度留空并重新分摊权重"
                )
        index = {}
        for key in ("classification", "industry", "trend", "etf", "quant", "options", "dragon_tiger"):
            index[key] = {}
            for row in sources[key]:
                identity = row.get("instrument_id") if key in {"trend", "quant"} else row.get("code")
                index[key].setdefault(identity, []).append(row)
        # Only retain immutable same-day industry evidence when latest-only memberships cannot be reconstructed.
        previous = self.repo.read(market, day)["items"]
        retained = {
            r["instrument_id"]: r["signals"]["industry"].get("evidence", {})
            for r in previous
            if r["signals"].get("industry", {}).get("status") != "unavailable"
        }
        candidates = []
        retained_count = 0
        for stock in self.repo.instruments(market):
            identity, code = stock["id"], stock["code"]
            trend_rows = index["trend"].get(identity, [])
            industry_rows = sorted(index["industry"].get(code, []), key=lambda row: row.get("industry_code", ""))
            inputs = {}
            if trend_rows:
                anchor = next((r for r in trend_rows if r.get("trend_period", 20) == 20), trend_rows[0])
                inputs["trend"] = dict(anchor, periods=trend_rows)
            if industry_rows:
                inputs["industry"] = dict(industry_rows[0], industries=industry_rows)
            elif identity in retained:
                inputs["industry"] = retained[identity]
                retained_count += 1
            for key in ("etf", "quant", "options", "dragon_tiger"):
                rows = index[key].get(identity if key == "quant" else code, [])
                inputs[key] = rows[0] if rows else None
            if not any(inputs.values()):
                continue
            classification = index["classification"].get(code, [])
            inputs["macro"] = adapt(
                sources["macro"][0] if sources["macro"] else None,
                classification[0] if classification else None,
                market,
            )
            inputs["sentiment"] = sources["sentiment"][0] if sources["sentiment"] else None
            signals = {
                key: v2.evaluate(
                    key,
                    json_safe(inputs.get(key)),
                    availability[key].get("reason", "本股票或市场在该日期无对应核心指标"),
                )
                for key in v2.WEIGHTS
            }
            result = v2.aggregate(signals, policy)
            if result["eligible"]:
                candidates.append(
                    dict(instrument_id=identity, code=code, **result, algorithm_version=v2.VERSION, generated_at=now)
                )
        if retained_count:
            availability["industry"]["retained_signal_count"] = retained_count
            availability["industry"]["reason"] = "当前行业成分无法重建，保留该日已保存的正式行业证据"
        candidates.sort(key=v2.confidence_key)
        selected = candidates[: policy["max_signals"]]
        rows = [{k: v for k, v in row.items() if k != "code"} for row in selected]
        availability["selection"] = dict(
            candidate_count=len(candidates),
            selected_count=len(rows),
            max_signals=policy["max_signals"],
            elapsed_seconds=round(perf_counter() - started, 4),
            order="主要维度正向一致性→主要维度数→综合分→代码",
        )
        published = self.repo.save(
            market,
            day,
            rows,
            dict(
                generated_at=now,
                algorithm_version=v2.VERSION,
                source_availability=json_safe(availability),
                rules=policy,
            ),
        )
        return dict(
            status="completed" if published else "superseded",
            market=market,
            trade_date=day.isoformat(),
            count=len(rows),
            eligible_count=len(rows),
            candidate_count=len(candidates),
            elapsed_seconds=round(perf_counter() - started, 4),
            source_availability=json_safe(availability),
        )

    def ranking(
        self,
        market,
        day=None,
        min_score=0,
        min_signals=None,
        industry=None,
        lifecycle=None,
        early_only=False,
        top_industry=False,
        strong_only=False,
        limit=200,
    ):
        response = self.repo.read(market, day)
        rows = response["items"]
        response["rules"] = response.get("rules") or c.current_rules()
        if min_signals is None:
            min_signals = response["rules"]["min_signals"]

        def industry_top(row):
            evidence = row["signals"]["industry"]["evidence"]
            return any(
                r.get("strength_rank") is not None and r["strength_rank"] <= c.TOP_INDUSTRY
                for r in evidence.get("industries", [evidence])
            )

        response["summary"] = dict(
            total=len(rows),
            candidate_count=response.get("source_availability", {})
            .get("selection", {})
            .get("candidate_count", len(rows)),
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
            industry_names = {
                value
                for item in industry_facts.get("industries", [industry_facts])
                for value in (item.get("industry_code"), item.get("industry_name"))
            }
            if industry and industry not in industry_names:
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
        if (response.get("algorithm_version") or "").startswith("confluence_v2"):
            from finance_analysis.confluence.v2 import confidence_key

            selected.sort(key=confidence_key)
        response["total"] = len(selected)
        response["items"] = selected[:limit]
        return response
