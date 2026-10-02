"""Pure, independently testable cutoff, comparison and evidence rules."""

import hashlib
import json
import math
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.market_review import trading_calendar as calendar
from .config import OutlookConfig

NY = ZoneInfo("America/New_York")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def timestamp(value):
    if not value:
        return None
    try:
        return coerce_aware_utc(
            datetime.fromisoformat(str(value).replace("Z", "+00:00")) if not isinstance(value, datetime) else value
        )
    except (TypeError, ValueError):
        return None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def schedule(event):
    return {
        key: (
            getattr(event, key).isoformat()
            if isinstance(getattr(event, key), (datetime,))
            else str(getattr(event, key)) if key == "event_date" else getattr(event, key)
        )
        for key in ("symbol", "reporting_period", "event_date", "event_datetime", "market_session")
    }


def trading_days(start, end):
    # Unlike legacy callers this feature must fail closed when a real holiday calendar is missing.
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("US exchange calendar unavailable")
    return calendar.get_trading_days_between("us", start, end)


def matches_schedule(event, schedule_hash, frozen_event=None):
    current = schedule(event)
    # Provider completion of the already-researched quarter is not a rescheduled release.
    return digest(current) == schedule_hash or current == frozen_event


def event_window(event):
    day = event.event_date
    session = (event.market_session or "").lower()
    days = trading_days(day, day + timedelta(days=14))
    known = session in {"bmo", "amc"} and day in days
    target = next(d for d in days if d > day) if session != "bmo" else days[0]
    earliest = datetime.combine(day, time.min, NY)
    if session == "amc" and known:
        earliest = calendar.get_market_session_bounds("us", day)[1]
    explicit = timestamp(event.event_datetime)
    cutoff = min(explicit, earliest) if explicit else earliest
    # A confirmed explicit release time is usable for BMO, but never after the opening bell.
    if explicit and session == "bmo" and known:
        cutoff = min(explicit, calendar.get_market_session_bounds("us", day)[0])
    return dict(
        cutoff=cutoff.astimezone(timezone.utc),
        target_trading_date=target,
        provisional=not known,
        assumption=None if known else "会话未知/非交易日，暂按下一正常交易日；不作高置信度标记",
    )


def released(event, now, window):
    from .facts import has_actual

    return has_actual(event) or now >= window["cutoff"]


def compare(value, estimate, metric, currency="USD", config=None):
    config = config or OutlookConfig()
    value, estimate = number(value), number(estimate)
    if value is None or estimate is None:
        return "unknown"
    tolerance = abs(estimate) * (
        config.eps_relative_tolerance if metric == "eps" else config.revenue_relative_tolerance
    )
    if metric == "eps" and currency == "USD":
        tolerance = max(tolerance, config.eps_absolute_usd)
    if abs(value - estimate) <= tolerance + 1e-12:
        return "meet"
    return "beat" if value > estimate else "miss"


def clean_research(bundle, cutoff, retrieved_at):
    """Reject future evidence, keep conflicts separate, never promote a source list to search proof."""
    sources, rejected = [], []
    for source in bundle.get("sources", []):
        if not isinstance(source, dict) or not source.get("source_id"):
            continue
        url = str(source.get("url") or "")
        published = timestamp(source.get("published_at"))
        if not url.startswith(("https://", "http://")) or (published and published > cutoff):
            rejected.append(source.get("source_id"))
            continue
        if published and published < cutoff - timedelta(days=30) and source.get("source_type") != "official_guidance":
            rejected.append(source["source_id"])
            continue
        sources.append({**source, "retrieved_at": retrieved_at.isoformat(), "publication_known": published is not None})
    ids = {s["source_id"] for s in sources}
    facts = [
        f
        for f in bundle.get("facts", [])
        if isinstance(f, dict) and f.get("source_ids") and set(f["source_ids"]).issubset(ids)
    ]
    period = bundle.get("reporting_period")
    if not isinstance(period, dict) or not period.get("source_ids") or not set(period["source_ids"]).issubset(ids):
        period = None
    return {
        "sources": sources,
        "facts": facts,
        "conflicts": [
            c
            for c in bundle.get("conflicts", [])
            if isinstance(c, dict) and c.get("source_ids") and set(c["source_ids"]).issubset(ids)
        ],
        "consensus": {
            metric: value
            for metric, value in (bundle.get("consensus") or {}).items()
            if metric in {"eps", "revenue"}
            and isinstance(value, dict)
            and value.get("source_ids")
            and set(value["source_ids"]).issubset(ids)
            and (timestamp(value.get("as_of")) is None or timestamp(value["as_of"]) <= cutoff)
        },
        "reporting_period": period,
        "excluded_source_ids": rejected,
        # Free text has no source IDs: do not let rejected evidence re-enter via this field.
        "uncertainties": [] if rejected else bundle.get("uncertainties", []),
        "publication_unknown": any(not s["publication_known"] for s in sources),
    }


def research_quarter(bundle, event):
    """Resolve a missing fiscal quarter only from dated official evidence for this release."""
    period = bundle.get("reporting_period")
    if not isinstance(period, dict):
        return None
    sources = {s["source_id"]: s for s in bundle.get("sources", [])}
    cited = period.get("source_ids") or []
    value = period.get("value")
    if (
        isinstance(value, str)
        and re.fullmatch(r"\d{4}-Q[1-4]", value)
        and period.get("symbol") == event.symbol
        and period.get("event_date") == str(event.event_date)
        and cited
        and all(
            s in sources
            and sources[s]["publication_known"]
            and sources[s].get("source_type") in {"official", "official_guidance"}
            for s in cited
        )
        and not any(c.get("metric") == "reporting_period" for c in bundle.get("conflicts", []))
    ):
        return value
    return None


def comparable(estimate, quarter, metric):
    return bool(
        estimate
        and number(estimate.get("value")) is not None
        and quarter
        and estimate.get("quarter") == quarter
        and estimate.get("currency")
        and estimate.get("unit")
        and estimate.get("source")
        and estimate.get("as_of")
        and (metric != "eps" or estimate.get("basis") in {"gaap", "adjusted"})
    )


def normalize_prediction(raw, context, config=None):
    """Downgrade only unsupported sections; derive return and beats using a single policy."""
    config = config or OutlookConfig()
    missing = list(context.get("missing_data", []))
    quarter = context["event"]["reporting_period"]
    judgments = {}
    for metric in ("eps", "revenue"):
        estimate = context["consensus"].get(metric)
        section = raw.get(metric)
        predicted = number(section.get("expected_value")) if isinstance(section, dict) else None
        valid = comparable(estimate, quarter, metric)
        judgments[metric] = {
            "expected_value": predicted if valid else None,
            "judgment": (
                compare(predicted, estimate["value"], metric, estimate["currency"], config) if valid else "unknown"
            ),
            "consensus": estimate,
        }
        if not valid:
            missing.append(f"{metric}: 一致预期缺失或季度/币种/单位/口径/更新时间不可比较")
    guidance = raw.get("guidance", "unknown")
    if not isinstance(guidance, str) or guidance not in {"above", "inline", "below", "unknown"}:
        guidance = "unknown"
    if not context.get("guidance_evidence"):
        guidance = "unknown"
    confidence = max(0, min(10, number(raw.get("earnings_confidence")) or 0))
    if not raw.get("earnings_confidence_reason") or not raw.get("earnings_reason"):
        confidence = min(confidence, 6)
    if (
        not context.get("guidance_evidence")
        and not context.get("historical_earnings")
        and not context.get("operating_evidence")
    ):
        confidence = min(confidence, 6)
    if any(j["judgment"] == "unknown" for j in judgments.values()) or context.get("evidence_limited"):
        confidence = min(confidence, 6)
    reaction_confidence = max(0, min(10, number(raw.get("reaction_confidence")) or 0))
    if not raw.get("reaction_confidence_reason") or not raw.get("reaction_reason"):
        reaction_confidence = min(reaction_confidence, 6)
    price = context.get("reference_price")
    close, low, high = [number(raw.get(k)) for k in ("expected_close", "intraday_low", "intraday_high")]
    valid_price = bool(price and close and low and high and 0 < low <= close <= high)
    if not valid_price:
        close = low = high = None
        reaction_confidence = 0
        missing.append("首日价格预测缺少参考价或区间无效")
    if context["provisional"] or context.get("evidence_limited") or context.get("price_stale"):
        reaction_confidence = min(reaction_confidence, 6)
    pct = (close / price - 1) * 100 if valid_price else None
    direction = "uncertain" if pct is None else "up" if pct > 1 else "down" if pct < -1 else "flat"
    scenarios = []
    for name in ("optimistic", "base", "pessimistic"):
        s = next((s for s in (raw.get("scenarios") or []) if isinstance(s, dict) and s.get("name") == name), {})
        sl, sh = number(s.get("low")), number(s.get("high"))
        good = valid_price and sl is not None and sh is not None and 0 < sl <= sh
        scenarios.append(
            dict(
                name=name,
                conditions=s.get("conditions") or "资料不足",
                reaction_reason=s.get("reaction_reason") or "资料不足",
                low=sl if good else None,
                high=sh if good else None,
            )
        )
    return dict(
        **judgments,
        guidance=guidance,
        conclusion=str(raw.get("conclusion") or "资料不足"),
        earnings_reason=str(raw.get("earnings_reason") or "资料不足"),
        earnings_confidence=confidence,
        earnings_confidence_reason=str(raw.get("earnings_confidence_reason") or "资料不足"),
        expected_close=close,
        intraday_low=low,
        intraday_high=high,
        expected_return_pct=pct,
        response_direction=direction,
        reaction_confidence=reaction_confidence,
        reaction_reason=str(raw.get("reaction_reason") or "资料不足"),
        reaction_confidence_reason=str(raw.get("reaction_confidence_reason") or "资料不足"),
        scenarios=scenarios,
        missing_data=missing,
        uncertainties=raw.get("uncertainties", []),
        tolerance=vars(config),
        **{
            k: context[k]
            for k in (
                "reference_price",
                "reference_price_at",
                "reference_price_session",
                "target_trading_date",
                "provisional",
                "assumption",
            )
        },
    )


def review_prediction(prediction, actual, context, config=None):
    if config is None:
        fields = OutlookConfig.__dataclass_fields__
        config = OutlookConfig(**{k: v for k, v in prediction.get("tolerance", {}).items() if k in fields})
    result = {"status": "pending", "eps": "unknown", "revenue": "unknown", "actual": actual}
    for metric in ("eps", "revenue"):
        estimate = prediction[metric].get("consensus")
        observed = actual.get(metric)
        if (
            comparable(estimate, context["event"]["reporting_period"], metric)
            and observed
            and all(observed.get(k) == estimate.get(k) for k in ("quarter", "currency", "unit", "basis"))
        ):
            result[metric] = compare(observed.get("value"), estimate["value"], metric, estimate["currency"], config)
    bar = actual.get("ohlc")
    if bar and prediction.get("expected_close") and context.get("reference_price"):
        ref = context["reference_price"]
        pct = (bar["close"] / ref - 1) * 100
        direction = "up" if pct > 1 else "down" if pct < -1 else "flat"
        result.update(
            close_error=prediction["expected_close"] - bar["close"],
            close_error_pct=(prediction["expected_close"] / bar["close"] - 1) * 100,
            actual_return_pct=pct,
            direction_correct=direction == prediction["response_direction"],
            range_covered=prediction["intraday_low"] <= bar["low"] and prediction["intraday_high"] >= bar["high"],
        )
    if bar and all(result[m] != "unknown" for m in ("eps", "revenue")):
        result["status"] = "completed"
    return result
