"""Shared lossless binary representation and stable diagnostic JSON encoding."""

import base64
import json


def binary_content(data) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}


def text_or_binary(data: bytes) -> dict:
    try:
        return {"encoding": "utf-8", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return binary_content(data)


def json_default(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return binary_content(value)
    # datetime/date, Decimal and UUID have stable, lossless string representations.
    return str(value)


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, default=json_default, separators=(",", ":")).encode()
