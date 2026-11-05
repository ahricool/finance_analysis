"""Independent CSV reader for request contract tests; not application code."""

import csv
import io
import json
import re


def tables(prompt):
    return {
        name: list(csv.DictReader(io.StringIO(body)))
        for name, fence, body in re.findall(r"^## ([^\n]+)\n\n?(`{3,})csv\n(.*?)^\2\n", prompt, re.S | re.M)
    }


def read_reference(prompt):
    result, refs = {}, {}
    for name, rows in tables(prompt).items():
        for raw in rows:
            row = {}
            for field, value in raw.items():
                if field in {"ref", "parent_ref"}:
                    continue
                try:
                    value = None if value == "NA" else json.loads(value)
                except ValueError:
                    pass
                if isinstance(value, str) and value.startswith("@data/"):
                    continue
                target = row
                bits = field.split(".")
                for bit in bits[:-1]:
                    if not isinstance(target.get(bit), dict):
                        target[bit] = {}
                    target = target[bit]
                target[bits[-1]] = value
            if name == "data":
                result = row
            else:
                parent = refs[raw["parent_ref"]]
                bits = name.rsplit("/", 1)[1].split(".")
                for bit in bits[:-1]:
                    parent = parent.setdefault(bit, {})
                parent.setdefault(bits[-1], []).append(row.get("value") if set(row) == {"value"} else row)
            refs[raw["ref"]] = row
    return result
