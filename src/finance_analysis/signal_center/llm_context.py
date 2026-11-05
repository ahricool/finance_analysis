"""Bounded conclusions for the LLM; full upstream evidence stays in the frozen snapshot."""

import json

from finance_analysis.signal_center.inputs import build_evidence

MAX_PROMPT_CHARS = 40_000
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


class PromptTooLarge(ValueError):
    """A safe size diagnostic that can be persisted without exposing prompt contents."""


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
        context_version="conclusions_v1",
        market=snapshot["market"],
        signal_date=snapshot["signal_date"],
        source_availability={
            key: project(row, "status data_as_of count")
            for key, row in snapshot.get("source_availability", {}).items()
        },
        market_regime=[project(row, REGIME_FIELDS) for row in snapshot["market_regime"]],
        candidates=candidates,
    )
    if screening is not None:
        view["screening"] = screening
    # Only facts visible to this request may pass the final evidence validator.
    # Do not send this expanded index: the input already contains every value.
    view["evidence_catalog"] = build_evidence(view)
    return view


def serialize(view, system_prompt):
    payload = {key: value for key, value in view.items() if key != "evidence_catalog"}
    prompt = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    length = len(system_prompt) + 7 + len(prompt)
    if length > MAX_PROMPT_CHARS:
        raise PromptTooLarge(f"Signal Center prompt exceeds {MAX_PROMPT_CHARS} characters ({length})")
    return prompt
