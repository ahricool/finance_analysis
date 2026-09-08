"""Logical identity and source merging; no SDK or persistence objects."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

CALENDAR_TYPES = ("earnings", "macro")
CALENDAR_TYPE_LABELS = {"earnings": "财报", "macro": "宏观"}
EVENT_FIELDS = (
    "provider",
    "provider_event_id",
    "calendar_type",
    "market",
    "symbol",
    "counter_name",
    "event_type",
    "reporting_period",
    "event_date",
    "event_datetime",
    "market_session",
    "title",
    "content",
    "currency",
    "eps_estimate",
    "reported_eps",
    "eps_surprise_pct",
)


def day(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def normalize_session(value: Any) -> str:
    if "盘前" in str(value or ""):
        return "bmo"
    if "盘后" in str(value or ""):
        return "amc"
    if "盘中" in str(value or ""):
        return "during_market"
    text = re.sub(r"[^a-z]", "", str(value or "").lower())
    if text in {"bmo", "beforemarketopen", "beforeopen", "premarket", "beforetrading"}:
        return "bmo"
    if text in {"amc", "aftermarketclose", "afterclose", "postmarket", "aftertrading"}:
        return "amc"
    if text in {"dmh", "duringmarket", "duringmarkethours", "duringtrading", "intraday"}:
        return "during_market"
    return "unknown"


def macro_type(name: str) -> str:
    """Explicit cross-language aliases; preserve frequency/core/release distinctions."""
    text = str(name or "").lower().strip()
    base = None
    if re.search(r"(?<![a-z])cpi(?![a-z])|consumer price index|消费者物价|消费者价格|消费价格", text):
        base = "cpi"
    elif re.search(r"non.?farm payroll|non.?farm employment|非农就业|非农人口", text):
        base = "nonfarm_payrolls"
    elif re.search(
        r"^fomc$|fomc.*(rate|decision)|fed.*interest rate|fed(?:eral)? funds target rate|联邦基金利率|美联储.*利率",
        text,
    ):
        base = "fomc_rate_decision"
    elif re.search(r"(?<![a-z])pce(?![a-z])|personal consumption expenditure|个人消费支出", text):
        base = "pce"
    elif re.search(r"(?<![a-z])gdp(?![a-z])|gross domestic product|国内生产总值", text):
        base = "gdp"
    if base:
        qualifiers = []
        for label, pattern in (
            ("core", r"core|核心"),
            ("yoy", r"yoy|y/y|\byy\b|year.over.year|年率|同比"),
            ("mom", r"mom|m/m|\bmm\b|month.over.month|月率|环比"),
            ("qoq", r"qoq|q/q|\bqq\b|quarter.over.quarter|季率"),
            ("advance", r"advance|初值"),
            ("preliminary", r"prelim|修正值"),
            ("final", r"final|终值"),
            ("upper", r"upper|上限"),
            ("lower", r"lower|下限"),
        ):
            if re.search(pattern, text):
                qualifiers.append(label)
        return "_".join([base, *qualifiers])
    text = re.sub(r"^(united states|u\.s\.|us|美国)\s*", "", text)
    return re.sub(r"[^\w]+", "_", text).strip("_")[:64]


def source_payloads(event: Mapping[str, Any]) -> dict:
    raw = event.get("raw_payload_json") or {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    return dict(raw)


def with_source(event: Mapping[str, Any], raw: Any = None, *, observed_at: datetime | None = None) -> dict:
    result = dict(event)
    provider = result["provider"]
    result["raw_payload_json"] = {
        provider: {"normalized": {key: result.get(key) for key in EVENT_FIELDS}, "raw": raw or {}},
    }
    if observed_at is not None:
        result["raw_payload_json"][provider]["observed_at"] = observed_at.isoformat()
    return result


def has_value(value: Any) -> bool:
    return value is not None and value != "" and value != "unknown"


def merge_sources(*events: Mapping[str, Any]) -> dict:
    """Latest snapshot per source; Yahoo wins populated canonical fields, including across runs."""
    sources = {}
    for event in events:
        payload = source_payloads(event)
        if not payload:
            payload = with_source(event)["raw_payload_json"]
        for provider in ("yfinance", "longbridge"):
            if provider in payload:
                incoming = payload[provider]
                previous = sources.get(provider, {}).get("normalized", {})
                normalized = dict(previous)
                current = incoming.get("normalized", {})
                if current.get("event_date") and str(current["event_date"]) != str(previous.get("event_date")):
                    normalized["event_datetime"] = None
                normalized.update({k: v for k, v in incoming.get("normalized", {}).items() if has_value(v)})
                sources[provider] = {**incoming, "normalized": normalized}
    primary = "yfinance" if "yfinance" in sources else "longbridge"
    secondary = sources.get("longbridge", {}).get("normalized", {})
    yahoo = sources.get("yfinance", {}).get("normalized", {})
    values = {key: secondary.get(key) for key in EVENT_FIELDS}
    values.update({key: value for key, value in yahoo.items() if key in EVENT_FIELDS and has_value(value)})
    values["provider"] = primary
    values["provider_event_id"] = sources[primary]["normalized"].get("provider_event_id")
    if has_value(yahoo.get("event_date")) and str(yahoo.get("event_date")) != str(secondary.get("event_date")):
        values["event_datetime"] = yahoo.get("event_datetime")
    values["market_session"] = values.get("market_session") or "unknown"
    conflicts = {
        key: {"yfinance": yahoo[key], "longbridge": secondary[key]}
        for key in EVENT_FIELDS
        if key not in {"provider", "provider_event_id", "title", "content"}
        and has_value(yahoo.get(key))
        and has_value(secondary.get(key))
        and str(yahoo[key]) != str(secondary[key])
    }
    if conflicts:
        sources["conflicts"] = conflicts
    values["raw_payload_json"] = sources
    return values


def match_rank(left: Mapping[str, Any], right: Mapping[str, Any], *, as_of: date) -> int:
    if any(left.get(k) != right.get(k) for k in ("calendar_type", "market", "symbol")):
        return 0
    lp, rp = left.get("reporting_period"), right.get("reporting_period")
    if lp and rp and lp != rp:
        return 0
    distance = abs((day(left["event_date"]) - day(right["event_date"])).days)
    if left["calendar_type"] == "macro":
        if left.get("event_type") != right.get("event_type"):
            return 0
        if lp and rp:
            return 3 if distance <= 7 else 0
        left_time, right_time = left.get("event_datetime"), right.get("event_datetime")
        if left_time and right_time:
            times = [datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in (left_time, right_time)]
            times = [value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value for value in times]
            if abs((times[0] - times[1]).total_seconds()) > 7200:
                return 0
        return 1 if distance == 0 else 0
    if lp and rp:
        return 3
    for provider in ("yfinance", "longbridge"):
        a = source_payloads(left).get(provider, {}).get("normalized", {}).get("provider_event_id")
        b = source_payloads(right).get(provider, {}).get("normalized", {}).get("provider_event_id")
        if a and a == b and distance <= 45:
            return 2
    # Seven-day grace handles delayed reports/corrections across the release date.
    # A 21-day bound avoids conflating adjacent quarters; ambiguous matches are not guessed.
    return int(distance <= 21 and min(day(left["event_date"]), day(right["event_date"])) >= as_of - timedelta(days=7))


def merge_events(events: list[dict], *, as_of: date) -> list[dict]:
    merged: list[dict] = []
    for event in sorted(events, key=lambda item: (item["provider"] != "yfinance", str(item["event_date"]))):
        ranks = [match_rank(existing, event, as_of=as_of) for existing in merged]
        best = max(ranks, default=0)
        candidates = [i for i, rank in enumerate(ranks) if best and rank == best]
        if len(candidates) == 1:
            index = candidates[0]
            merged[index] = merge_sources(merged[index], event)
        else:
            merged.append(merge_sources(event))
    return merged
