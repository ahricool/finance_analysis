"""Read persisted provider facts without inventing reporting basis or publication time."""

import json
import math


def raw_facts(event):
    get = event.get if isinstance(event, dict) else lambda key: getattr(event, key, None)
    raw = get("raw_payload_json") or {}
    try:
        raw = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    facts = dict(raw.get("earnings_facts") or {})
    for group in ("actual", "consensus"):
        facts[group] = dict(facts.get(group) or {})
    source = raw.get("longbridge") or {}
    payload = source.get("raw") or {}
    normalized = source.get("normalized") or {}
    for detail in payload.get("details") or []:
        kind = detail.get("value_type")
        if kind not in {"estimate_eps", "estimate_revenue", "actual_eps", "actual_revenue"}:
            continue
        try:
            value = float(detail.get("value_raw"))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(value):
            continue
        group = "consensus" if kind.startswith("estimate") else "actual"
        metric = "eps" if kind.endswith("eps") else "revenue"
        facts[group].setdefault(
            metric,
            dict(
                value=value,
                quarter=normalized.get("reporting_period"),
                currency=normalized.get("currency") or payload.get("currency"),
                unit="per_share" if metric == "eps" else "currency_units",
                basis=None,
                source="longbridge",
                as_of=None,
                observed_at=source.get("observed_at"),
                note="保留提供方原始数值；未提供的季度、币种、EPS口径及发布时间不可推断",
            ),
        )
    return facts


def has_actual(event):
    get = event.get if isinstance(event, dict) else lambda key: getattr(event, key, None)
    return get("reported_eps") is not None or any(
        raw_facts(event).get("actual", {}).get(k) is not None for k in ("eps", "revenue")
    )
