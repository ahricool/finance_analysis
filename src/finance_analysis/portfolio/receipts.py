"""Lossless server-generated portfolio receipts and stable request fingerprints."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal


def _encode(value):
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    raise TypeError(type(value).__name__)


def _decode(value):
    if set(value) == {"$decimal"}:
        return Decimal(value["$decimal"])
    if set(value) == {"$datetime"}:
        return datetime.fromisoformat(value["$datetime"])
    return value


def encode_receipt(value):
    return json.dumps(value, default=_encode, sort_keys=True, ensure_ascii=False)


def decode_receipt(value):
    return json.loads(value, object_hook=_decode)


def request_hash(payload):
    return hashlib.sha256(encode_receipt(payload).encode()).hexdigest()
