"""Lossless JSON normalization and shared-field factoring for latest previews."""

from copy import deepcopy
from datetime import date, datetime
import math

from finance_analysis.core.time import ensure_aware_utc, utc_isoformat, utc_now


def json_ready(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return str(value)


def observed_at(payload):
    stamp = (payload.get("run_started_at") or payload.get("preview_time")
             or payload.get("generated_at") or payload.get("observed_at"))
    return ensure_aware_utc(datetime.fromisoformat(stamp.replace("Z", "+00:00"))) if stamp else utc_now()


def merge_dict(left, right):
    result = deepcopy(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def factor_common(rows, *, exclude=("code", "name", "symbol")):
    """Store equal scalar/parameter subtrees once, without recalculating evidence.

    Missing and null remain distinct. Unequal floats and per-stock diagnostics are
    retained verbatim. Keys used for lookup/name joins always stay on each row.
    """
    if len(rows) < 2:
        return {}, deepcopy(rows)

    def common(objects, ignored=()):
        result = {}
        for key in objects[0].keys() - set(ignored):
            if not all(key in obj for obj in objects):
                continue
            values = [obj[key] for obj in objects]
            if all(exact_equal(value, values[0]) for value in values):
                result[key] = deepcopy(values[0])
            elif all(isinstance(value, dict) for value in values):
                nested = common(values)
                if nested:
                    result[key] = nested
        return result

    shared = common(rows, exclude)

    def subtract(row, base):
        output = deepcopy(row)
        for key, value in base.items():
            if exact_equal(output[key], value):
                output.pop(key)
            else:
                output[key] = subtract(output[key], value)
        return output

    return shared, [subtract(row, shared) for row in rows]


def exact_equal(left, right):
    """Python equates False and 0 even inside nested containers; JSON must not."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(exact_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, float):
        return left.hex() == right.hex()
    return left == right
