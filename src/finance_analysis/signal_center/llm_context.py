"""Selected conclusions for the LLM; full upstream evidence stays in the frozen snapshot."""

import csv
import io
import math

from finance_analysis.llm.prompting import fenced_csv

from finance_analysis.signal_center.prompt_template import TABLE_GUIDE

from finance_analysis.signal_center.inputs import build_evidence

TREND_FIELDS = (
    "trade_date rank rank_change state setup alpha_score trend_lifecycle trend_duration_days "
    "fragility_score reference_price"
)
TREND_FEATURES = "rs_10d distance_from_ma20 breakout_distance volume_ratio trend_quality drawdown_20d"
ETF_FIELDS = "trade_date rank state composite_score entry_score overheated ret_5d ret_10d rank_change_1d"
INDUSTRY_FIELDS = (
    "trade_date industry_code industry_name strength_rank strength_score state trend_rank "
    "rank_change_1d rank_change_5d"
)
CONFLUENCE_FIELDS = (
    "trade_date confluence_score eligible strong_confluence positive_signal_count "
    "available_signal_count available_weight"
)
REGIME_FIELDS = "trade_date source market_regime market_score data_coverage regime benchmark_trend"


def project(row, fields):
    """An omitted/null upstream field remains unavailable, never an invented default."""
    return {key: row[key] for key in fields.split() if key in row and row[key] is not None}


def conclusions(snapshot, symbols, screening=None):
    """Project both fresh and previously frozen inputs without changing candidate membership."""
    selected = set(symbols)
    candidates = []
    for candidate in snapshot["candidates"]:
        if candidate["symbol"] not in selected:
            continue
        trends = {}
        for period, row in candidate.get("trends", {}).items():
            trend = project(row, TREND_FIELDS)
            trend["features"] = project(row.get("features") or {}, TREND_FEATURES)
            trends[period] = trend
        candidates.append(
            dict(
                symbol=candidate["symbol"],
                name=candidate["name"],
                instrument_type=candidate["instrument_type"],
                nominated_by=list(candidate["nominated_by"]),
                trends=trends,
                etf=project(candidate["etf"], ETF_FIELDS) if candidate.get("etf") else None,
                industry=[project(row, INDUSTRY_FIELDS) for row in candidate.get("industry", [])],
                confluence=(
                    project(candidate["confluence"], CONFLUENCE_FIELDS) if candidate.get("confluence") else None
                ),
            )
        )
    view = dict(
        context_version="tables_v2",
        market=snapshot["market"],
        signal_date=snapshot["signal_date"],
        source_availability={
            key: project(row, "status data_as_of") for key, row in snapshot.get("source_availability", {}).items()
        },
        market_regime=[project(row, REGIME_FIELDS) for row in snapshot["market_regime"]],
        candidates=candidates,
    )
    if screening is not None:
        view["screening"] = screening
    # Only facts visible to this request may pass the final evidence validator.
    # Do not send this expanded index: the input already contains every value.
    view = rounded(view)
    view["evidence_catalog"] = build_evidence(view)
    return view


def rounded(value, key=""):
    if isinstance(value, dict):
        return {k: rounded(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v, key) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        ratios = {
            "rs_10d",
            "distance_from_ma20",
            "breakout_distance",
            "drawdown_20d",
            "ret_5d",
            "ret_10d",
            "data_coverage",
        }
        return round(value, 4 if key in ratios else 2)
    return value


def table(name, rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(
            [
                "NA" if row.get(key) is None else str(row[key]).lower() if isinstance(row[key], bool) else row[key]
                for key in columns
            ]
        )
    return f"\n## {name}\n\n" + fenced_csv(stream.getvalue())


def serialize(view):
    prompt = TABLE_GUIDE + table("metadata", [{"market": view["market"], "signal_date": view["signal_date"]}])
    prompt += table("source_availability", [dict(source=k, **v) for k, v in view["source_availability"].items()])
    prompt += table("market_regime", [dict(ref=f"market_regime.{i}", **v) for i, v in enumerate(view["market_regime"])])
    prompt += table(
        "candidates",
        [
            dict(
                symbol=c["symbol"],
                name=c["name"],
                instrument_type=c["instrument_type"],
                nominated_by="|".join(c["nominated_by"]),
            )
            for c in view["candidates"]
        ],
    )
    for source in ("trends", "etf", "industry", "confluence"):
        rows = []
        for c in view["candidates"]:
            value = c[source]
            entries = (
                value.items() if source == "trends" else enumerate(value) if source == "industry" else [(None, value)]
            )
            for index, row in entries:
                if not row:
                    continue
                ref = f"{c['symbol']}.{source}" + (f".{index}" if index is not None else "")
                flat = {k: v for k, v in row.items() if k != "features"}
                flat.update({f"features.{k}": v for k, v in row.get("features", {}).items()})
                rows.append(dict(ref=ref, **flat))
        prompt += table(source, rows)
    if "screening" in view:
        prompt += table(
            "screening", [dict(symbols="|".join(r["symbols"]), reason=r["reason"]) for r in view["screening"]]
        )
    return prompt
