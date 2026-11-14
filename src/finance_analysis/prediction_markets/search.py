"""Name/ticker search, without catalog persistence or inferred stock associations."""

import hashlib
import json
import math
import re
from urllib.parse import quote

from finance_analysis.integrations.polymarket.client import PolymarketError
from .live import get_live_service


def search_terms(symbol, name):
    # Legal suffixes are not useful search terms; never invent an English translation.
    name = re.sub(r"(?:,?\s+(?:Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited))+$", "", (name or "").strip(), flags=re.I)
    ticker = symbol.rsplit(".", 1)[0]
    return list(dict.fromkeys(q for q in (name, ticker) if q and q != symbol))


def event_projection(raw):
    volume = raw.get("volume24hr")
    try:
        volume = float(volume)
        if not math.isfinite(volume) or volume < 0:
            volume = None
    except (ValueError, TypeError):
        volume = None
    return dict(
        event_id=str(raw["id"]),
        title=str(raw["title"]),
        url="https://polymarket.com/event/" + quote(str(raw["slug"]), safe=""),
        end_at=raw.get("endDate"),
        closed=raw.get("closed"),
        volume_24h=volume,
    )


def search_stock(symbol, name, service=None):
    service = service or get_live_service()
    terms = search_terms(symbol, name)
    fingerprint = hashlib.sha256(json.dumps([symbol, terms], ensure_ascii=False).encode()).hexdigest()

    def load():
        items, seen, failures = [], set(), 0
        for term in terms:
            try:
                rows = service.client.search(term)
                for raw in rows:
                    if not isinstance(raw, dict) or not all(raw.get(k) for k in ("id", "title", "slug")):
                        raise PolymarketError("invalid_search_event")
                    event_id = str(raw["id"])
                    if raw.get("closed") or raw.get("archived") or event_id in seen:
                        continue
                    seen.add(event_id)
                    items.append(event_projection(raw))
            except PolymarketError:
                failures += 1
        if failures == len(terms):
            raise PolymarketError("search_unavailable")
        return dict(symbol=symbol, queries=terms, items=items[:20], partial=bool(failures), sort="official_relevance")

    return service.cached("stock-search:v1:" + fingerprint, service.config.search_ttl, load)
