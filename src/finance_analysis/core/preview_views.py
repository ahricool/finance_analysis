"""Compact JSON encoding shared by research read APIs."""

import json


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
