"""Fixed-host public HTTP; Gamma keyset and Data API v2 cursors are distinct."""

import math
import time
from urllib.parse import quote

import httpx

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
PROTOCOLS = ("v1", "v2")


class PolymarketError(RuntimeError):
    pass


class Client:
    def __init__(self, http=None, sleep=time.sleep):
        self.http = http or httpx.Client(
            timeout=20, follow_redirects=False, limits=httpx.Limits(max_connections=4, max_keepalive_connections=4)
        )
        self.sleep = sleep

    def close(self):
        self.http.close()

    def get(self, host, path, params=None):
        for attempt in range(3):
            try:
                response = self.http.get(host + path, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                    if delay > 30:
                        raise PolymarketError("upstream_rate_limited")
                    self.sleep(max(0, delay))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                if isinstance(exc, httpx.TransportError) and attempt < 2:
                    self.sleep(2**attempt)
                    continue
                # Do not log response bodies (may contain complete prices).
                raise PolymarketError(f"upstream_{type(exc).__name__}") from None
        raise PolymarketError("upstream_unavailable")

    def tags(self):
        offset, seen = 0, set()
        while True:
            rows = self.get(
                GAMMA,
                "/tags",
                {"limit": 100, "offset": offset, "order": "id", "ascending": "true", "include_template": "true"},
            )
            if not isinstance(rows, list):
                raise PolymarketError("invalid_tag_page")
            if not rows:
                return
            ids = {str(r["id"]) for r in rows}
            if ids <= seen:
                raise PolymarketError("repeated_tag_page")
            seen.update(ids)
            yield from rows
            offset += len(rows)

    def events(self, tag_id):
        # Event collection has no documented version filter. Enumerate the version-aware
        # market collection too, discovering parent event IDs for BOTH protocols.
        seen = set()
        params = {"tag_id": tag_id, "closed": "false", "limit": 100}
        for event in self._keyset("/events/keyset", "events", params):
            seen.add(str(event["id"]))
            yield event
        params = {**params, "version": list(PROTOCOLS)}
        for market in self._keyset("/markets/keyset", "markets", params):
            for event in market.get("events") or []:
                event_id = str(event["id"])
                if event_id not in seen:
                    seen.add(event_id)
                    yield self.event(event_id)

    def _keyset(self, path, key, params):
        params, cursors = dict(params), set()
        while True:
            page = self.get(GAMMA, path, params)
            if not isinstance(page, dict) or not isinstance(page.get(key), list):
                raise PolymarketError("invalid_catalog_page")
            yield from page[key]
            cursor = page.get("next_cursor")
            if not cursor:
                return
            if cursor in cursors:
                raise PolymarketError("repeated_catalog_cursor")
            cursors.add(cursor)
            params["after_cursor"] = cursor

    def event(self, event_id):
        return self.get(GAMMA, "/events/" + quote(str(event_id), safe=""))

    def event_slug(self, slug):
        return self.get(GAMMA, "/events/slug/" + quote(slug, safe=""))

    def history(self, asset, *, interval=None, start=None, end=None, as_of=None, bucket_seconds=None):
        if sum(v is not None for v in (interval, start, as_of)) != 1:
            raise ValueError("Exactly one history window is required")
        if start is not None and (start <= 0 or end is None or end <= start):
            raise ValueError("Explicit history requires positive start/end")
        if start is not None and end - start > 15 * 86400:
            points = []
            while start < end:
                stop = min(end, start + 15 * 86400)
                points.extend(self.history(asset, start=start, end=stop, bucket_seconds=bucket_seconds))
                start = stop
            return deduplicate(points)
        params = {"token_id": str(asset), "limit": 10000}
        params.update(
            {
                k: v
                for k, v in dict(
                    interval=interval, start=start, end=end, as_of=as_of, bucket_seconds=bucket_seconds
                ).items()
                if v is not None
            }
        )
        points, cursors = [], set()
        while True:
            page = self.get(DATA, "/v2/prices-history", params)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list) or "pagination" not in page:
                raise PolymarketError("invalid_history_page")
            for p in page["data"]:
                price = probability(p.get("price"))
                if price is not None:
                    points.append(
                        dict(
                            timestamp=int(p["timestamp"]), price=price, resolution_seconds=int(p["resolution_seconds"])
                        )
                    )
            cursor = page["pagination"].get("next_cursor")
            if not cursor:
                if page["pagination"].get("has_more"):
                    raise PolymarketError("missing_history_cursor")
                return deduplicate(points)
            if cursor in cursors:
                raise PolymarketError("repeated_history_cursor")
            cursors.add(cursor)
            params["cursor"] = cursor


def probability(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= 1 else None
    except (ValueError, TypeError):
        return None


def deduplicate(points):
    return sorted({p["timestamp"]: p for p in points}.values(), key=lambda p: p["timestamp"])
