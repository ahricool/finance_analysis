"""Deterministic, deliberately conservative rules. Never calls an LLM."""

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

RULE_VERSION = "catalog-1"
MATCH_VERSION = "matching-1"
TAG_GROUPS = {
    "finance": {"finance", "financials", "stocks", "stock-market", "markets", "fed", "interest-rates"},
    "business": {"business", "ipos", "ipo", "earnings", "companies", "mergers"},
    "economy": {"economy", "economics", "inflation", "recession", "gdp", "unemployment"},
    "technology": {"tech", "technology", "ai", "artificial-intelligence", "semiconductors"},
    "policy": {"tariffs", "trade-war", "regulation", "economic-policy", "monetary-policy", "fiscal-policy"},
}
EXCLUDED_TAGS = {"sports", "nba", "nfl", "soccer", "tennis", "entertainment", "movies", "music", "celebrities"}
POLICY = re.compile(r"\b(tariff|trade|export|import|regulat|tax|fiscal|monetary|rate|inflation|sanction)", re.I)
MICRO_CRYPTO = re.compile(r"(bitcoin|btc|ethereum|eth|solana|xrp).*(up or down|\d+\s*(minute|min)\b)", re.I)
PRICE = re.compile(r"\b(stock price|share price|market cap|close above|close below|reach \$)", re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def tag_group(slug, label=""):
    key = (slug or label).strip().lower().replace(" ", "-")
    return next((group for group, slugs in TAG_GROUPS.items() if key in slugs), "other")


def decide(event, tags):
    visible = [t for t in tags if t["visible"] and t["tag_id"] in event["tag_ids"]]
    slugs = {t["slug"] for t in tags if t["tag_id"] in event["tag_ids"]}
    title = event["title"]
    if not visible:
        return False, "no_visible_tag"
    if slugs & EXCLUDED_TAGS:
        return False, "sports_or_entertainment"
    if MICRO_CRYPTO.search(title):
        return False, "minute_crypto_template"
    if all(t["rule_group"] == "policy" for t in visible) and not POLICY.search(title + " " + event["description"]):
        return False, "policy_without_economic_theme"
    return True, "price_prediction" if PRICE.search(title) else "selected_tag"


def timestamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def project_event(raw):
    """Strict allowlist: nested markets, prices, volumes and rolling updatedAt never persist."""
    if raw.get("id") is None or not raw.get("title"):
        raise ValueError("Missing event identity/title")
    tags = sorted({str(t["id"]) for t in raw.get("tags", []) if t.get("id") is not None})
    result = dict(
        event_id=str(raw["id"]),
        slug=str(raw.get("slug") or ""),
        title=str(raw["title"]),
        description=str(raw.get("description") or "")[:6000],
        tag_ids=tags,
        start_at=timestamp(raw.get("startDate")),
        end_at=timestamp(raw.get("endDate")),
        closed=raw.get("closed") if isinstance(raw.get("closed"), bool) else None,
        archived=raw.get("archived") if isinstance(raw.get("archived"), bool) else None,
    )
    result["semantic_hash"] = digest({k: result[k] for k in ("title", "description", "tag_ids", "start_at", "end_at")})
    return result


def import_slug(value):
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"polymarket.com", "www.polymarket.com"}
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/event/")
        ):
            raise ValueError("仅支持官方 https://polymarket.com/event/slug 链接或 slug")
        value = parsed.path.removeprefix("/event/").rstrip("/")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("无效的事件 slug")
    return value


def recalls(event, profile):
    text = (event["title"] + " " + event["description"]).casefold()
    # Public-name normalization only, never an invented business description.
    company = re.sub(
        r"(?i)[, .]+(?:incorporated|inc|corporation|corp|limited|ltd|plc)\.?$", "", profile["name"]
    ).strip()
    terms = [profile["name"], company, *profile.get("aliases", []), *profile.get("industries", [])]
    # Short ticker words such as AI/ON are never arbitrary substring matches.
    ticker = profile["symbol"].split(".")[0]
    if len(ticker) >= 3:
        terms.append(ticker)
    for term in terms:
        term = str(term).strip().casefold()
        if len(term) < 3 and term.isascii():
            continue
        if term and (
            re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) if term.isascii() else term in text
        ):
            return True
    return False


def matching_version(event, tags):
    public_tags = sorted((t["tag_id"], t["slug"], t["label"]) for t in tags if t["tag_id"] in event["tag_ids"])
    return digest([event["semantic_hash"], MATCH_VERSION, public_tags])
