"""Deterministic daily allocations; no inferred seat partition or overlapping 3-day sums."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json

from .config import VERSION

MONEY = ("net_value", "buy_value", "sell_value", "org_net_value", "hot_money_net_value")
CENT = Decimal("0.01")


def concept_id(name):
    return sha256(name.encode()).hexdigest()[:20]


def split_amount(value, count):
    """Allocate integer cents; deterministic sorted-concept remainder preserves exact totals."""
    if value is None:
        return [None] * count
    total = Decimal(value).quantize(CENT)
    cents = int(total * 100)
    base, remainder = divmod(abs(cents), count)
    sign = -1 if cents < 0 else 1
    return [str(Decimal(sign * (base + (i < remainder))) / 100) for i in range(count)]


def sum_known(values):
    values = list(values)
    return None if any(v is None for v in values) else float(sum((Decimal(str(v)) for v in values), Decimal(0)))


def selected_rows(sources, board, period):
    source = sources.get("org" if board == "org" else "all")
    if not source:
        return [], False, 0
    rows = [dict(r) for r in source["rows"] if r["range_days"] == period]
    excluded = 0
    if board == "hot_money":
        excluded = sum(r["hot_money_net_value"] is None for r in rows)
        rows = [r for r in rows if r["hot_money_net_value"] is not None]
    for row in rows:
        row["stock_net_value"] = row["net_value"]
        if board != "all":
            row["net_value"] = row["org_net_value" if board == "org" else "hot_money_net_value"]
            # The API buy/sell fields are stock-wide, not institutional/hot-money gross amounts.
            row["buy_value"] = row["sell_value"] = None
    return rows, True, excluded


def allocate(rows):
    result = []
    for row in rows:
        names = row["concepts"] or ["未分类"]
        parts = {field: split_amount(row[field], len(names)) for field in MONEY}
        for index, name in enumerate(names):
            result.append(
                {
                    **row,
                    "concept_id": concept_id(name),
                    "concept_name": name,
                    "allocation_count": len(names),
                    "original_net_value": row["net_value"],
                    **{field: parts[field][index] for field in MONEY},
                }
            )
    return result


def calculate(batches, dates, board="all", period=1):
    """One immutable query response contains all chart and drill-down evidence."""
    if board not in ("all", "org", "hot_money") or period not in (1, 3):
        raise ValueError("Invalid observation scope")
    if period == 3:
        dates = dates[-1:]
    evidence, missing, daily, excluded = [], [], {}, 0
    source_quality = []
    for day in dates:
        batch = batches.get(day)
        rows, available, skipped = selected_rows(batch["sources"] if batch else {}, board, period)
        excluded += skipped
        if batch:
            source_quality.append(
                {
                    "trade_date": day.isoformat(),
                    "generated_at": batch["generated_at"],
                    "errors": batch.get("errors", {}),
                    "sources": {
                        k: {
                            key: v[key]
                            for key in ("quality", "upstream_count", "upstream_stock_count", "source_timestamp_ms")
                        }
                        for k, v in batch["sources"].items()
                    },
                }
            )
        if not available:
            missing.append(day.isoformat())
            continue
        allocations = allocate(rows)
        daily[day] = allocations
        evidence.extend({**a, "trade_date": day.isoformat()} for a in allocations)
    complete = not missing
    grouped = defaultdict(list)
    for row in evidence:
        grouped[row["concept_id"]].append(row)
    concepts = []
    for key, entries in grouped.items():
        values, running, valid = [], Decimal(0), True
        for day in dates:
            if day not in daily:
                valid = False
                values.append(None)
                continue
            value = sum_known(r["net_value"] for r in daily[day] if r["concept_id"] == key)
            valid = valid and value is not None
            if valid:
                running += Decimal(str(value))
            values.append(float(running) if valid else None)
        concepts.append(
            {
                "id": key,
                "name": entries[0]["concept_name"],
                "net_value": sum_known(r["net_value"] for r in entries) if complete else None,
                "org_net_value": sum_known(r["org_net_value"] for r in entries) if complete else None,
                "hot_money_net_value": sum_known(r["hot_money_net_value"] for r in entries) if complete else None,
                "stock_count": len({r["symbol"] for r in entries}),
                "values": values,
            }
        )
    concepts.sort(key=lambda r: (r["net_value"] is None, -(r["net_value"] or 0), r["id"]))
    stocks = {(r["trade_date"], r["symbol"]): r for r in evidence}
    # Restore stock-wide selected amounts before totals (allocations themselves contain split values).
    original = []
    for day in dates:
        batch = batches.get(day)
        rows, _, _ = selected_rows(batch["sources"] if batch else {}, board, period)
        original.extend(rows)
    summary = {field: sum_known(r[field] for r in original) if complete else None for field in MONEY}
    if board == "hot_money" and not original and excluded:
        summary = {field: None for field in MONEY}
    if board != "all":
        summary["buy_value"] = summary["sell_value"] = None
    positives = sorted(
        (r["net_value"] for r in concepts if r["net_value"] is not None and r["net_value"] > 0), reverse=True
    )
    summary.update(
        stock_count=len({k[1] for k in stocks}),
        top5_concentration=(
            sum(positives[:5]) / sum(positives)
            if positives and complete and all(c["net_value"] is not None for c in concepts)
            else None
        ),
    )
    versions = [(d.isoformat(), batches[d]["batch_id"]) for d in dates if d in batches]
    revision = sha256(
        json.dumps([VERSION, versions, board, period, [d.isoformat() for d in dates]]).encode()
    ).hexdigest()
    details = [
        dict(r, trade_date=d.isoformat())
        for d in dates
        if d in batches
        for r in batches[d]["sources"].get("hot_money", {}).get("details", [])
        if r["range_days"] == period
    ]
    return {
        "version": VERSION,
        "revision": revision,
        "board": board,
        "range_days": period,
        "trade_date": dates[-1].isoformat() if dates else None,
        "dates": [d.isoformat() for d in dates],
        "complete": complete,
        "missing_dates": missing,
        "excluded_undisclosed_count": excluded,
        "summary": summary,
        "concepts": concepts,
        "evidence": evidence,
        "hot_money_details": details,
        "source_quality": source_quality,
        "attribution": "independent_overlapping_categories",
        "source": "fuyao:/api/a-share/special-data/dragon-tiger-list",
        "unit": "CNY",
    }


def concept_detail(result, key):
    concept = next((c for c in result["concepts"] if c["id"] == key), None)
    if concept is None:
        return None
    groups = defaultdict(list)
    for row in result["evidence"]:
        if row["concept_id"] == key:
            groups[row["symbol"]].append(row)
    stocks = [
        {
            "symbol": symbol,
            "name": rows[0]["name"],
            "net_value": sum_known(r["net_value"] for r in rows) if result["complete"] else None,
            "rows": rows,
        }
        for symbol, rows in groups.items()
    ]
    stocks.sort(key=lambda r: (r["net_value"] is None, -(r["net_value"] or 0), r["symbol"]))
    return {"revision": result["revision"], "concept": concept, "stocks": stocks}
