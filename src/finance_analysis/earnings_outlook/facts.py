"""Read persisted provider facts without inventing reporting basis or publication time."""

import json
import math


def normalize_actual(fact, estimate, metric):
    """Convert explicit revenue scales only; never supply missing identity or basis."""
    if not isinstance(fact, dict) or isinstance(fact.get("value"), bool):
        return None
    fact = dict(fact)
    if metric != "revenue" or not estimate or fact.get("currency") != estimate.get("currency"):
        return fact
    currency = fact.get("currency")
    if not currency:
        return fact
    scales = {"currency_units": 1, currency: 1}
    for unit, scale in (("units", 1), ("thousand", 1e3), ("million", 1e6), ("billion", 1e9)):
        scales.update({unit: scale, f"{currency}_{unit}": scale})
    source, target = scales.get(fact.get("unit")), scales.get(estimate.get("unit"))
    if source is not None and target is not None:
        try:
            value = float(fact["value"]) * source / target
        except (KeyError, TypeError, ValueError):
            return fact
        if math.isfinite(value):
            fact.update(value=value, unit=estimate["unit"])
    return fact


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
