"""Latest ETF previews in PostgreSQL, independent of official snapshots."""

from datetime import timedelta

from finance_analysis.core.preview_storage import factor_common, json_ready, merge_dict, observed_at
from finance_analysis.core.preview_views import encode
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.research_preview import PreviewRepository
from finance_analysis.etf_rotation.universe import normalize_etf_market

PREVIEW_TTL_SECONDS = 86400
NAMESPACE = "etf_rotation"


def save_preview(market, payload, *, repository=None):
    ready = json_ready(payload)
    rows = ready.pop("items", [])
    shared, rows = factor_common(rows)
    ready["market"] = normalize_etf_market(market)
    # Internal count supports status without reading the universe.
    header = {"payload": ready, "item_count": len(rows), "trade_date": ready.get("trade_date")}
    try:
        (repository or PreviewRepository()).publish(
            NAMESPACE, ready["market"], 0, header,
            [{"kind": "stock", "item_key": row["code"], "summary": row} for row in rows],
            shared=shared, observed_at=observed_at(ready), expires_at=utc_now() + timedelta(seconds=PREVIEW_TTL_SECONDS),
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to save ETF Rotation preview for {market}") from exc


def _read(market, repository, **kwargs):
    return (repository or PreviewRepository()).read(NAMESPACE, normalize_etf_market(market), **kwargs)


def load_preview(market, *, repository=None):
    stored = _read(market, repository)
    return {**stored["header"]["payload"], "items": [
        merge_dict(stored["shared"], row["summary"]) for row in stored["items"]
    ]} if stored else None


def load_preview_view(market, field, *, repository=None):
    from finance_analysis.core.preview_metadata import preview_metadata

    if field == "status":
        stored = _read(market, repository, view="header")
        if not stored:
            return None
        result = preview_metadata(stored["header"]["payload"], rows_key="items")
        result["snapshot_count"] = stored["header"]["item_count"]
        return encode(result)
    if not field.startswith("stock:"):
        return None
    stored = _read(market, repository, kind="stock", item_key=field.removeprefix("stock:"))
    if not stored or not stored["items"] or stored["header"]["payload"].get("status") != "completed":
        return None
    header = stored["header"]["payload"]
    row = merge_dict(stored["shared"], stored["items"][0]["summary"])
    row["rank_total"] = header.get("rankable_count")
    return encode({"market": header["market"], "trade_date": header["trade_date"], "metadata": row,
                   "latest": row, "history": [], "market_snapshot": header.get("market_snapshot")})
