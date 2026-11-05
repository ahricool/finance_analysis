"""Decode transmitted CSV in test doubles, independently of production projection."""

import json
from tests.prompt_tables import tables as read_tables


def read_prompt(prompt):
    tables = read_tables(prompt)
    result = dict(tables["metadata"][0], candidates=[], market_regime=[])

    def values(row):
        result = {}
        for key, value in row.items():
            if value == "NA":
                continue
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass
            if key.startswith("features."):
                result.setdefault("features", {})[key[9:]] = value
            else:
                result[key] = value
        return result

    for row in tables["candidates"]:
        result["candidates"].append(
            dict(row, nominated_by=row["nominated_by"].split("|"), trends={}, etf=None, industry=[], confluence=None)
        )
    by_symbol = {c["symbol"]: c for c in result["candidates"]}
    for source in ("trends", "etf", "industry", "confluence", "market_regime"):
        for row in tables[source]:
            ref = row.pop("ref")
            data = values(row)
            if source == "market_regime":
                result[source].append(data)
                continue
            symbol, suffix = ref.split("." + source, 1)
            c = by_symbol[symbol]
            if source == "trends":
                c[source][suffix[1:]] = data
            elif source == "industry":
                c[source].append(data)
            else:
                c[source] = data
    return result
