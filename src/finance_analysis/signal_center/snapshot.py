"""Bounded candidate unions with original scores and explicit missing evidence."""

import logging
import math
from finance_analysis.core.time import utc_now
from finance_analysis.signal_center.context import candidate_context
from finance_analysis.confluence.service import json_safe

logger = logging.getLogger(__name__)
TOP = 20
DEPENDENCIES = {
    "trend": "trend_following",
    "quant": "quant_daily",
    "industry": "industry_strength",
    "etf": "etf_rotation",
}


def collect(repo, market, day):
    dependencies = repo.dependencies(market, day)
    instruments = repo.instruments(market)
    by_id = {r["id"]: r["code"] for r in instruments}
    stocks = {r["code"]: r for r in instruments}
    sources, availability = {}, {}
    for key in ("trend", "quant", "industry", "etf", "regime"):
        if key == "industry" and market == "US":
            sources[key] = []
            availability[key] = dict(status="unsupported", data_as_of=None, generated_at=None)
            continue
        dep = dependencies.get(DEPENDENCIES.get(key), {})
        try:
            rows = getattr(repo, key)(market, day)
            as_of = max((r["trade_date"] for r in rows), default=None)
            generated = max((r.get("generated_at") for r in rows if r.get("generated_at")), default=None)
            active = dep.get("status") in {"pending", "processing", "retrying"}
            current = [r for r in rows if r["trade_date"] == day]
            if key == "regime":
                current = [
                    r
                    for r in current
                    if dependencies.get(DEPENDENCIES[r["source"]], {}).get("status")
                    not in {"pending", "processing", "retrying"}
                ]
            status = "running" if active else "available" if current else "stale" if rows else "missing"
            sources[key] = current if status == "available" else []
            availability[key] = dict(
                status=status, data_as_of=as_of, generated_at=generated, count=len(sources[key]), task=dep
            )
        except Exception:
            logger.exception("Signal Center source read failed: %s", key)
            sources[key] = []
            availability[key] = dict(status="failed", data_as_of=None, generated_at=None, count=0)

    trend = {by_id[r["instrument_id"]]: r for r in sources["trend"] if r["instrument_id"] in by_id}
    quant = {by_id[r["instrument_id"]]: r for r in sources["quant"] if r["instrument_id"] in by_id}
    industries = {}
    for row in sources["industry"]:
        if row["code"] in stocks:
            industries.setdefault(row["code"], []).append(row)
    ranked = sorted(
        (code for code in trend if trend[code].get("rank") is not None), key=lambda code: (trend[code]["rank"], code)
    )
    top_count = math.ceil(len(ranked) * 0.05)
    mover_threshold = max(1, math.ceil(len(ranked) * 0.10))
    movers = [
        code
        for code in ranked
        if trend[code].get("rank_change", 0) >= mover_threshold
        and top_count < trend[code]["rank"] <= math.ceil(len(ranked) * 0.10)
    ]
    movers.sort(key=lambda code: (-abs(trend[code]["rank_change"]), code))
    selections = {
        "trend": list(dict.fromkeys(ranked[:top_count] + movers[:TOP])),
        "quant": sorted(
            (code for code in quant if quant[code].get("universe_rank") is not None),
            key=lambda code: (quant[code]["universe_rank"], code),
        )[:3],
    }
    # Industry does not rank stocks independently: retain its existing materialized Trend rank.
    members = [
        r
        for rows in industries.values()
        for r in rows
        if r.get("strength_rank") is not None and r["strength_rank"] <= 5 and r.get("trend_rank") is not None
    ]
    members.sort(key=lambda r: (r["strength_rank"], r["trend_rank"], r["code"]))
    industry_codes = list(dict.fromkeys(r["industry_code"] for r in members))
    selections["industry"] = list(
        dict.fromkeys(
            r["code"]
            for industry in industry_codes
            for r in [row for row in members if row["industry_code"] == industry][:3]
        )
    )
    candidates = []
    for code in sorted(set().union(*map(set, selections.values()))):
        tr = trend.get(code)
        candidates.append(
            dict(
                symbol=code,
                market=market,
                name=stocks[code]["name"],
                nominated_by=[key for key, codes in selections.items() if code in codes],
                trend=tr,
                quant=quant.get(code),
                industry=industries.get(code, []),
                price=dict(value=tr["reference_price"], data_as_of=day, source="trend_reference_price") if tr else None,
                etf_relation=None,
            )
        )
    return json_safe(
        dict(
            schema_version=1,
            market=market,
            signal_date=day,
            captured_at=utc_now(),
            source_availability=availability,
            dependencies=dependencies,
            selection_rules=dict(
                trend_population=len(ranked),
                trend_top_percent=5,
                trend_top_count=top_count,
                trend_mover_count=min(TOP, len(movers)),
                trend_mover_threshold=mover_threshold,
                quant_top=3,
                industry_top=5,
                industry_components_per_group=3,
                etf_context_top=10,
            ),
            candidates=[candidate_context(c) for c in candidates],
            market_regime=sources["regime"],
            etf_context=sources["etf"],
            limitations=[
                "ETF仅为市场背景，无可靠股票映射",
                "Preview不属于正式日级输入",
                "行业仅CN且仅同代次最新成分；股票顺序复用成分表Trend rank",
                "分数保留来源量纲，不跨模块相加",
            ],
        )
    )


def ready(snapshot):
    return all(s["status"] in {"available", "unsupported"} for s in snapshot["source_availability"].values())


def sufficient(snapshot):
    available = snapshot["source_availability"]
    return bool(
        snapshot["candidates"]
        and snapshot["market_regime"]
        and any(available[k]["status"] == "available" for k in ("trend", "quant"))
    )
