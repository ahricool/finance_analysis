"""Fixed-host public HTTP; Gamma keyset and Data API v2 cursors are distinct."""

import math
import time
from urllib.parse import quote

import httpx

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"


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

    def get(self, host, path, params=None, *, attempts=3, timeout=None, max_delay=30):
        for attempt in range(attempts):
            try:
                response = self.http.get(
                    host + path, params=params, **({"timeout": timeout} if timeout is not None else {})
                )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                    if delay > max_delay:
                        raise PolymarketError("upstream_rate_limited")
                    self.sleep(max(0, delay))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                if isinstance(exc, httpx.TransportError) and attempt < attempts - 1:
                    self.sleep(2**attempt)
                    continue
                # Do not log response bodies (may contain complete prices).
                raise PolymarketError(f"upstream_{type(exc).__name__}") from None
        raise PolymarketError("upstream_unavailable")

    def search(self, query):
        """Official relevance order; bounded to the first 20 event hits per term."""
        page = self.get(
            GAMMA,
            "/public-search",
            {
                "q": query,
                "events_status": "active",
                "limit_per_type": 20,
                "page": 1,
                "search_tags": "false",
                "search_profiles": "false",
                "keep_closed_markets": 0,
            },
            attempts=2,
            timeout=6,
            max_delay=2,
        )
        if not isinstance(page, dict) or not isinstance(page.get("events") or [], list):
            raise PolymarketError("invalid_search_response")
        return (page.get("events") or [])[:20]

    def event(self, event_id):
        return self.get(GAMMA, "/events/" + quote(str(event_id), safe=""))

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
