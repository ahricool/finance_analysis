"""Latest Trend previews in PostgreSQL; official strategy history is independent."""

import json
from datetime import timedelta

from finance_analysis.core.preview_storage import exact_equal, factor_common, json_ready, merge_dict, observed_at
from finance_analysis.core.preview_views import encode
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.research_preview import PreviewRepository
from finance_analysis.trend_following.config import TREND_PERIODS
from finance_analysis.trend_following.read_models import FEATURE_FIELDS, SCORE_COMPONENT_PATHS
from finance_analysis.trend_following.universe import normalize_market

PREVIEW_TTL_SECONDS = 86400
NAMESPACE = "trend_following"


def _scope(market, period):
    if period not in TREND_PERIODS:
        raise ValueError("trend_period must be 20, 40 or 60")
    return NAMESPACE, normalize_market(market), period


def save_preview(market, payload, *, repository=None):
    ready = json_ready(payload)
    rows = ready.pop("snapshots", [])
    period = ready.get("trend_period", 20)
    scope = _scope(market, period)
    ready.update(market=scope[1], trend_period=period, snapshot_count=len(rows))
    aliases = {feature: top for feature, top in (
        ("reference_price", "reference_price"), ("entry_score", "entry_score"),
        ("entry_type", "entry_type"), ("trend_period", "trend_period"), ("atr20", "atr"),
    ) if rows and all(feature in row.get("features", {}) and top in row
                      and exact_equal(row["features"][feature], row[top]) for row in rows)}
    for row in rows:
        for feature in aliases:
            row["features"].pop(feature)
        # Move (rather than copy) list scoring scalars out of the diagnostic JSON.
        # PostgreSQL can then serve ranking without detoasting each large detail.
        components = {}
        for name, path in SCORE_COMPONENT_PATHS:
            node = row.get("score_breakdown", {})
            for part in path[:-1]:
                node = node.get(part, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict) and path[-1] in node:
                components[name] = node.pop(path[-1])
        if components:
            row["_score_components"] = components
    common, rows = factor_common(rows)
    inherited = [key for key in common if key in ready and exact_equal(common[key], ready[key])]
    shared = {"values": {key: value for key, value in common.items() if key not in inherited},
              "header_fields": inherited, "feature_aliases": aliases}
    items = []
    for row in rows:
        detail = {key: row.pop(key) for key in ("score_breakdown", "fragility_breakdown", "reasons") if key in row}
        if "features" in row:
            features = row["features"]
            row["features"] = {key: value for key, value in features.items() if key in FEATURE_FIELDS}
            detail["features"] = {key: value for key, value in features.items() if key not in FEATURE_FIELDS}
        items.append({"kind": "stock", "item_key": row["code"], "summary": row, "detail": detail})
    try:
        (repository or PreviewRepository()).publish(
            *scope, ready, items, shared=shared, observed_at=observed_at(ready),
            expires_at=utc_now() + timedelta(seconds=PREVIEW_TTL_SECONDS),
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to save Trend Following preview for {market}") from exc


def _read(market, period, repository, **kwargs):
    return (repository or PreviewRepository()).read(*_scope(market, period), **kwargs)


def _row(stored, row, *, summary_only=False):
    shared = stored["shared"]
    common = {**shared["values"], **{key: stored["header"][key] for key in shared["header_fields"]}}
    if summary_only:
        from .table import ITEM_FIELDS

        fields = (*ITEM_FIELDS, "features", "_score_components", *shared["feature_aliases"].values())
        common = {key: value for key, value in common.items() if key in fields}
        if "features" in common:
            common["features"] = {key: value for key, value in common["features"].items() if key in FEATURE_FIELDS}
    result = merge_dict(common, merge_dict(row["summary"], row["detail"]))
    components = result.pop("_score_components", {})
    for name, path in SCORE_COMPONENT_PATHS:
        if name in components:
            node = result.setdefault("score_breakdown", {})
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = components[name]
    for feature, top in shared["feature_aliases"].items():
        if top in result:
            result.setdefault("features", {})[feature] = result[top]
    return result


def load_preview(market, *, trend_period=20, repository=None):
    stored = _read(market, trend_period, repository)
    return {**stored["header"], "snapshots": [_row(stored, row) for row in stored["items"]]} if stored else None


def load_preview_view(market, field, *, trend_period=20, repository=None):
    from finance_analysis.core.preview_metadata import preview_metadata
    from .table import snapshot_item, table_rows

    if field == "status":
        stored = _read(market, trend_period, repository, view="header")
        if not stored:
            return None
        result = preview_metadata(stored["header"], rows_key="snapshots")
        result["snapshot_count"] = stored["header"]["snapshot_count"]
        return encode(result)
    if field.startswith("stock:"):
        stored = _read(market, trend_period, repository, kind="stock", item_key=field.removeprefix("stock:"))
        if not stored or not stored["items"] or stored["header"].get("status") != "completed":
            return None
        header, row = stored["header"], _row(stored, stored["items"][0])
        return encode({
            "market": header["market"], "trade_date": header["trade_date"],
            "metadata": {"market": header["market"], "code": row["code"], "name": row.get("name") or row["code"]},
            "latest": row, "history": [], "market_context": {**header, "generated_at": header.get("preview_time")},
        })
    if field not in {"ranking", "states"}:
        return None
    stored = _read(market, trend_period, repository, kind="stock",
                   view="states" if field == "states" else "summary")
    if not stored:
        return None
    if field == "states":
        keys = ("code", "name", "rank", "state", "alpha_score", "fragility_score")
        common = stored["shared"]["values"]
        rows = [{key: row["summary"].get(key, common.get(key)) for key in keys} for row in stored["items"]]
        return encode({**stored["header"], "snapshots": rows})
    rows = [_row(stored, row, summary_only=True) for row in stored["items"]]
    projected = [snapshot_item(row) for row in rows]
    return encode({**stored["header"], "table": table_rows(projected)})


def load_preview_states(market, *, trend_period=20, repository=None):
    body = load_preview_view(market, "states", trend_period=trend_period, repository=repository)
    return json.loads(body) if body else None
