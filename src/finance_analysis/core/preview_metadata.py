"""Small read projection of the existing preview cache; no persistence or computation."""

from typing import Any


def preview_metadata(payload: dict[str, Any], *, rows_key: str) -> dict[str, Any]:
    fields = ("status", "market", "trade_date", "preview_time", "data_as_of", "provider")
    return {
        **{field: payload.get(field) for field in fields},
        "snapshot_count": len(payload.get(rows_key) or []),
        "warnings": payload.get("warnings") or [],
    }
