"""Read-only formal opportunity projection shared by downstream research consumers.

Never detect patterns here. Absence, incomplete coverage and an evaluated empty
opportunity set are distinct. Cross-period identities are one price fact.
"""

from copy import deepcopy
from datetime import date, datetime, timezone
from math import isfinite

from .opportunities import BRANCHES, VERSION

POLICY_VERSION = "formal_opportunities_v1"
CANDIDATE_LIMIT = 40
FIELDS = (
    "structure_id kind rule_version status quality_score trigger support invalidation "
    "distance_atr distance_pct first_confirmed_at data_as_of anchor_date anchor_close price_basis "
    "background_periods source_generated_at"
).split()


def day_value(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime):
            return None
        # SQLite test adapters drop timezone info; persisted production timestamps are UTC.
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def formal_document(row, day, cutoff=None):
    document = (row.get("features") or {}).get("opportunities")
    expected = day_value(day)
    generated = timestamp(row.get("generated_at"))
    before = timestamp(cutoff) if cutoff is not None else None
    if (
        not expected
        or day_value(row.get("trade_date")) != expected
        or row.get("trend_period") not in (10, 20, 40)
        or not isinstance(document, dict)
        or document.get("version") != VERSION
        or document.get("code", row.get("code")) != row.get("code")
        or not isinstance(document.get("branches"), list)
        or document.get("history_status") not in {"complete", "partial"}
        or document.get("preview") is not False
        or day_value(document.get("data_as_of")) != expected
        or (cutoff is not None and (before is None or generated is None or generated >= before))
    ):
        return None
    return document


def formal_opportunities(rows, day, cutoff=None):
    """Return stock-level coverage plus valid branches, stable under input permutations."""
    stocks = {}
    for row in rows:
        document = formal_document(row, day, cutoff)
        code = row.get("code")
        if document is None or not code:
            continue
        item = stocks.setdefault(code, dict(code=code, branches=[], covered_periods=[], primary=None))
        item["covered_periods"].append(row["trend_period"])
        for branch in document.get("branches", []):
            if not isinstance(branch, dict):
                continue
            confirmed = day_value(branch.get("first_confirmed_at"))
            quality = branch.get("quality_score")
            if (
                branch.get("rule_version") != VERSION
                or branch.get("preview") is not False
                or branch.get("status") != "CONFIRMED"
                or branch.get("kind") not in BRANCHES
                or not isinstance(branch.get("structure_id"), str)
                or not branch["structure_id"]
                or day_value(branch.get("data_as_of")) != day_value(day)
                or confirmed is None
                or confirmed > day_value(day)
                or not numeric(quality)
                or not 0 <= quality <= 100
                or any(not numeric(branch.get(k)) or branch[k] <= 0 for k in ("trigger", "invalidation"))
            ):
                continue
            projected = {k: deepcopy(branch[k]) for k in FIELDS if k in branch}
            projected["background_periods"] = [row["trend_period"]]
            generated = timestamp(row.get("generated_at"))
            projected["source_generated_at"] = generated.isoformat() if generated else None
            item["branches"].append(projected)
    for item in stocks.values():
        # Stable tie-break chooses one intact branch record, never splices price/quality fields.
        groups = {}
        for branch in sorted(
            item["branches"],
            key=lambda b: (-b["quality_score"], b["kind"], b["structure_id"], b["background_periods"][0]),
        ):
            existing = groups.get(branch["structure_id"])
            if existing is None:
                groups[branch["structure_id"]] = branch
            else:
                existing["background_periods"] = sorted(
                    set(existing["background_periods"] + branch["background_periods"])
                )
        item["branches"] = list(groups.values())
        item["primary"] = item["branches"][0] if item["branches"] else None
        item["covered_periods"] = sorted(set(item["covered_periods"]))
    return sorted(
        stocks.values(),
        key=lambda i: (i["primary"] is None, -(i["primary"]["quality_score"] if i["primary"] else 0), i["code"]),
    )
