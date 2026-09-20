# -*- coding: utf-8 -*-
"""Shared LLM JSON parsing for structured reviews. Not an Intraday Judge."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def parse_llm_json_response(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a (possibly fenced or malformed) LLM response into a dict."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        snippet = stripped[start : end + 1] if start >= 0 and end > start else stripped
        try:
            from json_repair import repair_json

            parsed = json.loads(repair_json(snippet))
        except Exception:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_llm_batch_results(text: Optional[str], *, strict: bool = False) -> List[Dict[str, Any]]:
    """Parse ``{"results": [...]}`` or a bare JSON array of objects."""
    parsed = parse_llm_json_response(text)
    if isinstance(parsed, dict):
        results = parsed.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        if strict:
            raise ValueError("LLM response is not a JSON batch")
        return []

    if not text:
        if strict:
            raise ValueError("LLM response is empty")
        return []
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("[")
        end = stripped.rfind("]")
        snippet = stripped[start : end + 1] if start >= 0 and end > start else stripped
        try:
            from json_repair import repair_json

            loaded = json.loads(repair_json(snippet))
        except Exception:
            if strict:
                raise ValueError("LLM response is not a JSON batch") from None
            return []
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    if strict:
        raise ValueError("LLM response is not a JSON batch")
    return []
