# -*- coding: utf-8 -*-
"""
Shared data parsing and normalization helpers.
"""

import json
from typing import Any, Dict, Optional


_MODEL_PLACEHOLDER_VALUES = {"unknown", "error", "none", "null", "n/a"}


def normalize_model_used(value: Any) -> Optional[str]:
    """Normalize placeholder/empty model values to None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in _MODEL_PLACEHOLDER_VALUES:
        return None
    return text


def parse_json_field(value: Any) -> Any:
    """Best-effort JSON parse for string values; passthrough for others."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _non_empty_dict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return value if value else None


def extract_fundamental_context(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve fundamental_context from context snapshot, with optional fallback payload.
    """
    snapshot_obj = parse_json_field(context_snapshot)
    if isinstance(snapshot_obj, dict):
        enhanced = snapshot_obj.get("enhanced_context")
        if isinstance(enhanced, dict):
            fundamental = enhanced.get("fundamental_context")
            if isinstance(fundamental, dict):
                return fundamental

    fallback_obj = parse_json_field(fallback_fundamental_payload)
    if isinstance(fallback_obj, dict):
        return fallback_obj
    return None


def extract_fundamental_detail_fields(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Extract stable API-facing financial and dividend blocks from fundamental_context.
    """
    fundamental_ctx = extract_fundamental_context(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    if not isinstance(fundamental_ctx, dict):
        return {"financial_report": None, "dividend_metrics": None}

    earnings_block = fundamental_ctx.get("earnings")
    earnings_data = earnings_block.get("data") if isinstance(earnings_block, dict) else None
    if not isinstance(earnings_data, dict):
        return {"financial_report": None, "dividend_metrics": None}

    financial_report = _non_empty_dict(earnings_data.get("financial_report"))
    dividend_metrics = _non_empty_dict(earnings_data.get("dividend"))
    return {
        "financial_report": financial_report,
        "dividend_metrics": dividend_metrics,
    }
