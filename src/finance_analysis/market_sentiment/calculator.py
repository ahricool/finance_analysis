"""Deterministic calculations. No I/O, inferred limit-ups, or ladder posterior data."""

import math
import re
from datetime import time
from statistics import median

from .config import SentimentConfig


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def consecutive(row):
    """Require agreement with explicit continuous text; never reinterpret N天M板."""
    count, text = row.get("continue_day_cnt"), row.get("continue_day_text")
    if type(count) is not int or count < 1 or not isinstance(text, str):
        return None
    text = text.strip()
    if text == "首板":
        return 1 if count == 1 else None
    match = re.fullmatch(r"(\d+)连板", text)
    if match and int(match[1]) == count:
        return count
    match = re.fullmatch(r"(\d+)天(\d+)板", text)
    if match and int(match[1]) == int(match[2]) == count:
        return count
    return None


def normalized(row):
    result = dict(row)
    result["raw_scope_flags"] = {k: row.get(k) for k in ("is_st", "is_new")}
    for key in ("is_st", "is_new"):
        result[key] = row.get(key) if type(row.get(key)) is bool else None
    issues = []
    flags_valid = all(type(row.get(k)) is bool for k in ("is_st", "is_new"))
    result["in_scope"] = (not row["is_st"] and not row["is_new"]) if flags_valid else None
    if not flags_valid:
        issues.append("unknown_scope_flags")
    result["consecutive_boards"] = consecutive(row)
    if result["consecutive_boards"] is None:
        issues.append("unconfirmed_consecutive_boards")
    pct = number(row.get("price_change_ratio_pct"))
    result["price_change_ratio"] = pct / 100 if pct is not None else None
    raw_time = row.get("limit_up_time")
    parsed = None
    if isinstance(raw_time, str) and re.fullmatch(r"\d{2}:\d{2}", raw_time):
        try:
            parsed = time.fromisoformat(raw_time)
        except ValueError:
            pass
    if parsed is not None and not (time(9, 25) <= parsed <= time(11, 30) or time(13) <= parsed <= time(15)):
        parsed = None
    result["valid_limit_up_time"] = parsed.isoformat(timespec="minutes") if parsed else None
    if parsed is None:
        issues.append("invalid_limit_up_time")
    current, peak = number(row.get("seal_money")), number(row.get("max_seal_money"))
    result["seal_money"] = current if current is not None and current >= 0 else None
    result["max_seal_money"] = peak if peak is not None and peak >= 0 else None
    retention = current / peak if current is not None and current >= 0 and peak is not None and peak > 0 else None
    if retention is not None and not 0 <= retention <= 1:
        issues.append("abnormal_seal_retention")
        retention = None
    elif retention is None:
        issues.append("missing_seal_retention")
    result["seal_retention"] = retention
    reason = row.get("limit_up_reason")
    result["reason_group"] = reason.strip() if isinstance(reason, str) and reason.strip() else "未提供原因"
    result["quality_issues"] = issues
    return result


def ratio(n, d):
    return n / d if d else None


def metrics(rows, config=SentimentConfig()):
    scoped = [r for r in rows if r["in_scope"] is True]
    scope_ok = all(r["in_scope"] is not None for r in rows)
    boards_ok = scope_ok and all(r["consecutive_boards"] is not None for r in scoped)
    counts = {str(i): 0 for i in range(1, 7)} | {"7+": 0}
    for r in scoped:
        b = r["consecutive_boards"]
        if b is not None:
            counts[str(b) if b < 7 else "7+"] += 1
    valid_times = [r["valid_limit_up_time"] for r in scoped if r["valid_limit_up_time"] is not None]
    early = sum(t <= config.early_time.isoformat(timespec="minutes") for t in valid_times)
    retentions = [r["seal_retention"] for r in scoped if r["seal_retention"] is not None]
    amounts = [r["seal_money"] for r in scoped if r["seal_money"] is not None]
    reasons = {}
    for r in scoped:
        reasons[r["reason_group"]] = reasons.get(r["reason_group"], 0) + 1
    # Any unknown scope invalidates derived market aggregates, not the saved source.
    return {
        "upstream_total": len(rows),
        "excluded_st_count": sum(r.get("is_st") is True for r in rows),
        "excluded_new_count": sum(r.get("is_new") is True for r in rows),
        "excluded_union_count": sum(r.get("is_st") is True or r.get("is_new") is True for r in rows),
        "unknown_scope_count": sum(r["in_scope"] is None for r in rows),
        "scope_complete": scope_ok,
        "boards_complete": boards_ok,
        "limit_up_count": len(scoped) if scope_ok else None,
        "first_board_count": counts["1"] if boards_ok else None,
        "multi_board_count": sum(r["consecutive_boards"] >= 2 for r in scoped) if boards_ok else None,
        "highest_board": max((r["consecutive_boards"] for r in scoped), default=0) if boards_ok else None,
        "board_distribution": counts if boards_ok else {k: None for k in counts},
        "unconfirmed_board_count": sum(r["consecutive_boards"] is None for r in scoped),
        "early_limit_up_count": early if scope_ok else None,
        "valid_limit_up_time_count": len(valid_times) if scope_ok else None,
        "time_coverage": ratio(len(valid_times), len(scoped)) if scope_ok else None,
        "early_limit_up_ratio": ratio(early, len(valid_times)) if scope_ok else None,
        "seal_retention_median": median(retentions) if scope_ok and retentions else None,
        "valid_seal_retention_count": len(retentions) if scope_ok else None,
        "seal_retention_coverage": ratio(len(retentions), len(scoped)) if scope_ok else None,
        "seal_money_sum": (sum(amounts) if amounts or not scoped else None) if scope_ok else None,
        "valid_seal_money_count": len(amounts) if scope_ok else None,
        "seal_money_coverage": ratio(len(amounts), len(scoped)) if scope_ok else None,
        "reasons": (
            [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda x: (-x[1], x[0]))]
            if scope_ok
            else []
        ),
    }


def _promotion_scope(row):
    # Either exclusion flag alone proves non-membership, even if the other is unknown.
    # Keep the market-wide metrics' existing scope/quality rules unchanged.
    if row.get("is_st") is True or row.get("is_new") is True:
        return False
    return row["in_scope"]


def promotions(previous_rows, rows, previous_date, day):
    """Validate each prior-day cohort, then only its members' current outcomes.

    Both supplied pools have already passed complete-pagination validation.
    A missing prior source (None) is not a confirmed empty pool ([]).
    """
    output = {}
    current = {r["thscode"]: r for r in rows}
    for name, board in (("1_to_2", 1), ("2_to_3", 2), ("3_to_4", 3), ("multi", None)):
        complete = previous_rows is not None
        cohort = []
        for row in previous_rows or []:
            scope, height = _promotion_scope(row), row["consecutive_boards"]
            if scope is False:
                continue
            if height is not None and not (height == board if board is not None else height >= 2):
                continue
            # Unknowns cannot be discarded if they might belong to this denominator.
            if scope is None or height is None:
                complete = False
            else:
                cohort.append(row)

        passed = []
        for row in cohort:
            today = current.get(row["thscode"])
            if today is None or _promotion_scope(today) is False:
                continue
            if _promotion_scope(today) is None or today["consecutive_boards"] is None:
                complete = False
            elif today["consecutive_boards"] == row["consecutive_boards"] + 1:
                passed.append(row["thscode"])
        passed.sort()
        output[name] = {
            "source_date": previous_date,
            "target_date": day,
            "complete": complete,
            "numerator": len(passed) if complete else None,
            "denominator": len(cohort) if complete else None,
            "ratio": ratio(len(passed), len(cohort)) if complete else None,
            "promoted_codes": passed if complete else [],
            "not_promoted_codes": sorted({r["thscode"] for r in cohort} - set(passed)) if complete else [],
        }
    return output


def percentile(value, history):
    return 100 * (sum(x < value for x in history) + 0.5 * sum(x == value for x in history)) / len(history)


def quality_value(row, key, config):
    if row is None:
        return None
    if key == "promotion":
        p = row["promotions"]["multi"]
        return p["ratio"] if p["complete"] and (p["denominator"] or 0) >= config.minimum_promotion_cohort else None
    coverage = "time_coverage" if key == "early_limit_up_ratio" else "seal_retention_coverage"
    return row[key] if row[coverage] is not None and row[coverage] >= config.minimum_coverage else None


def classify(row, previous, recent, config=SentimentConfig()):
    h = row["heat_score"]
    if h is None:
        return "UNKNOWN", ["核心计数口径未确认或此前20个交易日完整有效历史不足"]
    if h <= config.ice:
        return "ICE", [f"热度 {h:.1f} ≤ {config.ice:g}"]
    p = previous
    comparable = p is not None and all(
        p.get(k) is not None for k in ("heat_score", "limit_up_count", "multi_board_count")
    )
    if comparable:
        delta = h - p["heat_score"]
        ldelta = row["limit_up_count"] - p["limit_up_count"]
        mdelta = row["multi_board_count"] - p["multi_board_count"]
        if (
            any(r and r.get("heat_score") is not None and r["heat_score"] >= config.active for r in recent)
            and delta <= -config.heat_change
            and ldelta < 0
            and mdelta < 0
        ):
            return "COOLING", [f"前3交易日有热度≥60；热度下降 {-delta:.1f} 分，涨停减少 {-ldelta}，连板减少 {-mdelta}"]
        if p["heat_score"] <= config.repair_base and delta >= config.heat_change and ldelta > 0 and mdelta >= 0:
            return "REPAIR", [
                f"昨日热度 {p['heat_score']:.1f}≤35；今日提高 {delta:.1f} 分，涨停增加 {ldelta}，连板未下降"
            ]
    if p is not None and (h >= config.active or (p.get("heat_score") is not None and p["heat_score"] >= config.active)):
        drops = []
        for key, label in (
            ("promotion", "连板晋级率"),
            ("early_limit_up_ratio", "早封率"),
            ("seal_retention_median", "封单留存"),
        ):
            now, before = quality_value(row, key, config), quality_value(p, key, config)
            if now is not None and before is not None and before - now >= config.quality_drop - 1e-12:
                drops.append(f"{label}下降 {(before - now) * 100:.1f} 个百分点")
        counts_diverge = (
            p.get("limit_up_count") is not None
            and p.get("multi_board_count") is not None
            and row["limit_up_count"] >= p["limit_up_count"]
            and row["multi_board_count"] < p["multi_board_count"]
        )
        if counts_diverge or len(drops) >= 2:
            return "DIVERGENCE", ["当日或昨日热度≥60", *(["涨停数未下降，但连板数下降"] if counts_diverge else drops)]
    if (
        p is not None
        and h >= config.climax
        and p.get("limit_up_count") is not None
        and p.get("multi_board_count") is not None
        and row["limit_up_count"] >= p["limit_up_count"]
        and row["multi_board_count"] >= p["multi_board_count"]
    ):
        confirmations = [
            label
            for key, label in (("early_limit_up_ratio", "早封率"), ("seal_retention_median", "封单留存"))
            if quality_value(row, key, config) is not None
            and quality_value(row, key, config) >= config.quality_confirmation
        ]
        if confirmations:
            return "CLIMAX", [f"热度 {h:.1f}≥85；涨停、连板数未下降", "、".join(confirmations) + "≥60%且覆盖率≥80%"]
    if h >= config.active:
        return "ACTIVE", [f"热度 {h:.1f} ≥ {config.active:g}"]
    return "NEUTRAL", [f"热度 {h:.1f}；未命中其他观察规则"]


def calculate(day, rows, sources, calculated, sessions, config=SentimentConfig()):
    """sessions includes every real exchange session through day, oldest first."""
    previous_day = sessions[-2] if len(sessions) >= 2 else None
    previous = calculated.get(previous_day)
    result = metrics(rows, config)
    result.update(
        trade_date=day,
        scope=config.scope,
        rule_version=config.version,
        early_time_threshold=config.early_time.isoformat(timespec="minutes"),
        heat_score=None,
    )
    result["promotions"] = promotions(sources.get(previous_day), rows, previous_day, day)
    past = [calculated.get(d) for d in sessions[-config.history_days - 1 : -1]]
    if (
        result["boards_complete"]
        and len(past) == config.history_days
        and all(r is not None and r["boards_complete"] for r in past)
    ):
        result["heat_score"] = config.limit_weight * percentile(
            result["limit_up_count"], [r["limit_up_count"] for r in past]
        ) + config.multi_weight * percentile(result["multi_board_count"], [r["multi_board_count"] for r in past])
    result["state"], result["state_reasons"] = classify(
        result, previous, [calculated.get(d) for d in sessions[-4:-1]], config
    )
    result["changes"] = {
        k: result[k] - previous[k] if previous and result[k] is not None and previous[k] is not None else None
        for k in (
            "limit_up_count",
            "first_board_count",
            "multi_board_count",
            "highest_board",
            "early_limit_up_ratio",
            "seal_retention_median",
            "heat_score",
        )
    }
    result["previous_trade_date"] = previous_day
    return result
