"""Lossless list projections; full diagnostic documents belong to security detail."""

from .read_models import FEATURE_FIELDS, RANKING_FIELDS, SCORE_COMPONENT_PATHS

ITEM_FIELDS = (*RANKING_FIELDS, "name", "entry_score", "entry_type",
               "rank_change_1d", "rank_change_3d", "rank_change_5d")


def snapshot_item(snapshot):
    features = snapshot.get("features") or {}
    projected = {key: features.get(key) for key in FEATURE_FIELDS}
    for key, path in SCORE_COMPONENT_PATHS:
        value = snapshot.get("score_breakdown") or {}
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            projected[key] = value
    return {**{key: snapshot.get(key) for key in ITEM_FIELDS}, "features": projected}


def table_rows(items):
    # Column names travel once. Nulls, booleans and numeric precision remain intact.
    features = [key for key in FEATURE_FIELDS if any(row.get("features", {}).get(key) is not None for row in items)]
    return {
        "columns": list(ITEM_FIELDS), "feature_columns": features,
        "rows": [[*(row.get(key) for key in ITEM_FIELDS),
                  *(row.get("features", {}).get(key) for key in features)] for row in items],
    }


def preview_views(payload):
    from finance_analysis.core.preview_metadata import preview_metadata

    summary = {key: value for key, value in payload.items() if key != "snapshots"}
    rows = payload.get("snapshots") or []
    return {
        "status": preview_metadata(payload, rows_key="snapshots"),
        "ranking": {**summary, "table": table_rows([snapshot_item(row) for row in rows])},
        "states": {**summary, "snapshots": [{key: row.get(key) for key in (
            "code", "name", "rank", "state", "alpha_score", "fragility_score",
        )} for row in rows]},
        **{f"stock:{row['code']}": {
            "market": payload["market"], "trade_date": payload["trade_date"],
            "metadata": {"market": payload["market"], "code": row["code"], "name": row.get("name") or row["code"]},
            "latest": row, "history": [],
            "market_context": {**summary, "generated_at": payload.get("preview_time")},
        } for row in rows if payload.get("status") == "completed"},
    }
