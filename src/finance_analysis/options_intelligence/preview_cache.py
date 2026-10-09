"""Latest intraday research in Redis, expiring at New York midnight. No DB writes."""

import json
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from finance_analysis.core.time import utc_now

logger = logging.getLogger(__name__)
PREVIEW_KEY = "options_intelligence:preview:v2:US"


def _client():
    import redis
    from finance_analysis.database.config import get_database_config

    return redis.Redis.from_url(
        get_database_config().redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    )


def load_preview(*, client=None, now=None, symbol=None, strict=False):
    now = now or utc_now()
    try:
        redis_client = client if client is not None else _client()
        raw = redis_client.get(PREVIEW_KEY)
        payload = json.loads(raw) if raw else None
        if (
            isinstance(payload, dict)
            and payload.get("trade_date") == now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        ):
            failures = {r["symbol"]: r for r in payload.get("failures", [])}
            payload["items"] = [
                {
                    **row,
                    **(
                        {"refresh_status": "failed", "refresh_reason": failures[row["symbol"]]["reason"]}
                        if row["symbol"] in failures
                        else {}
                    ),
                }
                for row in payload.get("items", [])
            ]
            if symbol is not None:
                summary = next((r for r in payload.get("items", []) if r["symbol"] == symbol), None)
                if summary is None:
                    return None
                raw = redis_client.get(f"{PREVIEW_KEY}:{payload['trade_date']}:{symbol}")
                detail = json.loads(raw) if raw else None
                # A concurrent publication may occur between these GETs; never mix generations.
                if not isinstance(detail, dict) or detail.get("computed_at") != summary.get("computed_at"):
                    return None
                failure = next((r for r in payload.get("failures", []) if r["symbol"] == symbol), None)
                if failure:
                    detail = {**detail, "refresh_status": "failed", "refresh_reason": failure["reason"]}
                return detail
            return payload
    except Exception:
        logger.exception("Options preview cache read failed")
        if strict:
            raise
    return None


def save_preview(payload, *, client=None, now=None, merge=False):
    now = now or utc_now()
    local = now.astimezone(ZoneInfo("America/New_York"))
    if payload["trade_date"] != local.date().isoformat():
        raise ValueError("Cannot publish an options preview from a previous session")
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ttl = max(1, int((midnight - local).total_seconds()))
    from .views import scan_view

    redis_client = client if client is not None else _client()
    previous = load_preview(client=redis_client, now=now, strict=True) if merge else None
    summaries = {r["symbol"]: r for r in (previous or {}).get("items", [])}
    summaries.update({r["symbol"]: scan_view(r) for r in payload["items"]})
    failures = {r["symbol"]: r for r in (previous or {}).get("failures", [])}
    for row in payload["items"]:
        failures.pop(row["symbol"], None)
    failures.update({r["symbol"]: r for r in payload.get("failures", [])})
    # A compact manifest keeps list reads independent of the size of 100 raw chains.
    # Publish details and manifest in a single transaction; Redis failure fails the task.
    transaction = redis_client.pipeline(transaction=True)
    for row in payload["items"]:
        transaction.set(
            f"{PREVIEW_KEY}:{payload['trade_date']}:{row['symbol']}",
            json.dumps(row, ensure_ascii=False, allow_nan=False),
            ex=ttl,
        )
    transaction.set(
        PREVIEW_KEY,
        json.dumps(
            {**payload, "items": list(summaries.values()), "failures": list(failures.values())},
            ensure_ascii=False,
            allow_nan=False,
        ),
        ex=ttl,
    )
    if not all(transaction.execute()):
        raise RuntimeError("Options preview Redis write failed")
