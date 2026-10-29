"""V2 formal candidate union, frozen before the first search-enabled LLM call."""

import logging
from finance_analysis.core.time import utc_now
from finance_analysis.confluence.service import json_safe
from finance_analysis.signal_center.context import candidate_context

logger = logging.getLogger(__name__)
DEPENDENCIES = {
    "trend20": "trend_following",
    "trend40": "trend_following",
    "trend60": "trend_following",
    "etf": "etf_rotation",
    "industry": "industry_strength",
    "confluence": "confluence",
}
ACTIVE = {"pending", "processing", "retrying"}


def screening_plan(candidates):
    # Canonical ordering makes the union independent of source read order and gives every source the same route.
    symbols = sorted(c["symbol"] for c in candidates)
    return dict(method="union_round_robin_v2", bucket_count=5, buckets=[symbols[i::5] for i in range(5)])


def collect(repo, market, day):
    dependencies = repo.dependencies(market, day)
    instruments = repo.instruments(market)
    stocks = {r["code"]: r for r in instruments}
    by_id = {r["id"]: r["code"] for r in instruments}
    sources, availability = {}, {}
    for key in (*DEPENDENCIES, "regime"):
        if key == "industry" and market == "US":
            sources[key] = []
            availability[key] = dict(status="unsupported", count=0, data_as_of=None, generated_at=None)
            continue
        dep = dependencies.get(DEPENDENCIES.get(key), {})
        try:
            generated = None
            if key.startswith("trend"):
                rows = repo.trend_period(market, day, int(key[5:]))
            elif key == "confluence":
                batch = repo.confluence(market, day)
                generated = batch.get("generated_at")
                rows = [dict(r, trade_date=batch["trade_date"]) for r in batch.get("items", [])]
            else:
                rows = getattr(repo, key)(market, day)
            current = [r for r in rows if r["trade_date"] == day]
            if key == "regime":
                current = [
                    r
                    for r in current
                    if dependencies.get("trend_following" if r["source"] == "trend" else "etf_rotation", {}).get(
                        "status"
                    )
                    not in ACTIVE
                ]
            as_of = max(
                (r["trade_date"] for r in rows),
                default=batch.get("trade_date") if key == "confluence" and generated else None,
            )
            generated = generated or max((r["generated_at"] for r in rows if r.get("generated_at")), default=None)
            status = (
                "running"
                if dep.get("status") in ACTIVE
                else (
                    "available"
                    if current or (key == "confluence" and generated and batch["trade_date"] == day)
                    else "stale" if rows or (key == "confluence" and generated) else "missing"
                )
            )
            sources[key] = current if status == "available" else []
            availability[key] = dict(
                status=status, data_as_of=as_of, generated_at=generated, count=len(sources[key]), task=dep
            )
        except Exception:
            logger.exception("Signal Center source read failed: %s", key)
            sources[key] = []
            availability[key] = dict(status="failed", data_as_of=None, generated_at=None, count=0)
    trends = {
        period: {by_id[r["instrument_id"]]: r for r in sources[f"trend{period}"] if r["instrument_id"] in by_id}
        for period in (20, 40, 60)
    }
    industry = {}
    for r in sources["industry"]:
        if r["code"] in stocks:
            industry.setdefault(r["code"], []).append(r)
    selections = {}
    for period, limit in ((20, 30), (40, 10), (60, 10)):
        ranked = sorted(
            (r for r in trends[period].values() if r.get("rank") is not None), key=lambda r: (r["rank"], r["code"])
        )
        selections[f"trend{period}"] = [r["code"] for r in ranked[:limit]]
    etfs = {r["code"]: r for r in sources["etf"] if r.get("code") in stocks}
    selections["etf"] = list(etfs)
    members = sorted(
        (
            r
            for rows in industry.values()
            for r in rows
            if r.get("strength_rank") is not None and r["strength_rank"] <= 5 and r.get("trend_rank") is not None
        ),
        key=lambda r: (r["strength_rank"], r["trend_rank"], r["code"]),
    )
    groups = dict.fromkeys(r["industry_code"] for r in members)
    selections["industry"] = list(
        dict.fromkeys(r["code"] for group in groups for r in [v for v in members if v["industry_code"] == group][:3])
    )
    # The manifest and stored rows are the frontend-visible formal generation (currently at most ten).
    confluence = {r["code"]: r for r in sources["confluence"] if r.get("code") in stocks}
    selections["confluence"] = list(confluence)
    candidates = []
    for code in sorted(set().union(*(set(v) for v in selections.values()))):
        periods = {
            str(period): candidate_context(dict(trend=rows[code], industry=[]))["trend"]
            for period, rows in trends.items()
            if code in rows
        }
        cf = confluence.get(code)
        if cf:
            # No direct Quant facts. The upstream published decision retains its original meaning.
            cf = {k: v for k, v in cf.items() if k not in {"signals", "reasons"}}
            cf["signals"] = {k: v for k, v in confluence[code].get("signals", {}).items() if k != "quant"}
            cf["limitations"] = ["共振为已发布整体结论，可能含上游Quant贡献；不提供Quant明细，不重复计为独立证据"]
        candidates.append(
            dict(
                symbol=code,
                market=market,
                name=stocks[code]["name"],
                instrument_type=stocks[code].get("instrument_type", "STOCK"),
                nominated_by=[key for key, codes in selections.items() if code in codes],
                trends=periods,
                etf=etfs.get(code),
                industry=industry.get(code, []),
                confluence=cf,
            )
        )
    snapshot = json_safe(
        dict(
            schema_version=2,
            market=market,
            signal_date=day,
            captured_at=utc_now(),
            source_availability=availability,
            dependencies=dependencies,
            candidates=candidates,
            screening_plan=screening_plan(candidates),
            market_regime=sources["regime"],
            selection_rules=dict(
                trend20_top=30,
                trend40_top=10,
                trend60_top=10,
                etf_top=10,
                industry_top=5,
                industry_per_group=3,
                confluence="all_published",
                quant=False,
            ),
            limitations=[
                "候选仅来自当日正式结果，Preview不参与",
                "不同模块分数不相加，共享底层事实不重复计为共振",
                "共振整体结论可能含上游Quant贡献，但本模块不读取Quant候选或明细",
            ],
        )
    )
    # Flat immutable facts make model references machine-checkable, including exact values and dates.
    snapshot["evidence_catalog"] = build_evidence(snapshot)
    return snapshot


def build_evidence(snapshot):
    catalog = {}

    def walk(value, path, symbol, source_date):
        if isinstance(value, dict):
            source_date = value.get("trade_date") or source_date
            for key, item in value.items():
                if key not in {
                    "generated_at",
                    "id",
                    "instrument_id",
                    "name",
                    "code",
                    "symbol",
                    "limitations",
                    "trade_date",
                    "updated_at",
                    "source_generated_at",
                    "source_module",
                }:
                    walk(item, f"{path}.{key}", symbol, source_date)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}.{index}", symbol, source_date)
        elif value is not None:
            catalog[path] = dict(symbol=symbol, field=path, value=value, data_as_of=source_date)

    for c in snapshot["candidates"]:
        for source in ("trends", "etf", "industry", "confluence"):
            walk(c[source], f"{c['symbol']}.{source}", c["symbol"], snapshot["signal_date"])
    walk(snapshot["market_regime"], "market_regime", None, snapshot["signal_date"])
    return catalog


def ready(snapshot):
    return all(s["status"] in {"available", "unsupported"} for s in snapshot["source_availability"].values())


def sufficient(snapshot):
    # Confluence is mandatory, including its valid empty generation; never freeze before it finishes.
    return bool(
        snapshot["candidates"]
        and snapshot["market_regime"]
        and snapshot["source_availability"]["confluence"]["status"] == "available"
    )
