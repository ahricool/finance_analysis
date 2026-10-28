"""Latest options research in dedicated DB tables, valid until New York midnight."""

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from finance_analysis.core.preview_storage import exact_equal, json_ready
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.research_preview import PreviewRepository
from .views import scan_view

logger = logging.getLogger(__name__)
NAMESPACE = "options_intelligence"


def load_preview(*, repository=None, now=None, symbol=None, strict=False):
    now = now or utc_now()
    try:
        stored = (repository or PreviewRepository()).read(
            NAMESPACE, "US", kind="stock", item_key=symbol, view="full" if symbol else "summary", now=now,
        )
        if not stored or stored["header"].get("trade_date") != now.astimezone(ZoneInfo("America/New_York")).date().isoformat():
            return None
        if symbol is None:
            return {**stored["header"], "items": [row["summary"] for row in stored["items"]]}
        if not stored["items"]:
            return None
        row = stored["items"][0]
        result = {**row["summary"], **row["detail"]}
        # The top event occurs once on disk and is restored to its original position.
        if "_top_event_index" in result:
            index = result.pop("_top_event_index")
            if index is not None:
                result["events"].insert(index, row["summary"]["top_event"])
        for key in result.pop("_summary_only", []):
            result.pop(key, None)
        return result
    except Exception:
        logger.exception("Options preview database read failed")
        if strict:
            raise
        return None


def save_preview(payload, *, repository=None, now=None, merge=False):
    now = now or utc_now()
    local = now.astimezone(ZoneInfo("America/New_York"))
    if payload["trade_date"] != local.date().isoformat():
        raise ValueError("Cannot publish an options preview from a previous session")
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ready = json_ready(payload)
    rows = ready.pop("items")
    ready.setdefault("failures", [])
    items = []
    for row in rows:
        summary = scan_view(row)
        detail = {key: value for key, value in row.items()
                  if key not in summary or not exact_equal(value, summary[key])}
        detail["_summary_only"] = sorted(summary.keys() - row.keys())
        if "events" in row:
            events = list(row["events"])
            top = summary["top_event"]
            index = events.index(top) if top is not None else None
            if index is not None:
                events.pop(index)
            detail.update(events=events, _top_event_index=index)
        items.append({"kind": "stock", "item_key": row["symbol"], "summary": summary, "detail": detail})

    def merge_header(previous, current):
        failures = {row["symbol"]: row for row in previous.get("failures", [])}
        for row in rows:
            failures.pop(row["symbol"], None)
        failures.update({row["symbol"]: row for row in current["failures"]})
        return {**current, "failures": list(failures.values())}

    (repository or PreviewRepository()).publish(
        NAMESPACE, "US", 0, ready, items, observed_at=now, expires_at=midnight,
        merge=merge, remove_keys=[row["symbol"] for row in ready["failures"]], merge_header=merge_header,
    )
