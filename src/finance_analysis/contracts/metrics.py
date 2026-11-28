"""Five-minute UTC ending boundaries shared by collection, storage and projection."""
from finance_analysis.integrations.crypto.binance import number

MINUTE = 60_000
STEP = 5 * MINUTE
HOUR = 12 * STEP
DAY = 24 * HOUR
LIST_METRIC_MAX_AGE = STEP + 15 * MINUTE
ENDPOINTS = {
    "accounts": "globalLongShortAccountRatio",
    "oi": "openInterestHist",
    "taker": "takerlongshortRatio",
    "top_accounts": "topLongShortAccountRatio",
    "top_positions": "topLongShortPositionRatio",
}


def aligned(stamp):
    return stamp // STEP * STEP


def normalize(source, rows, symbol, start, end):
    result = {}
    for row in rows:
        if row.get("symbol", symbol) != symbol:
            continue
        stamp = int(row["timestamp"])
        boundary = stamp + STEP if source == "taker" else stamp
        if boundary % STEP or not start <= boundary <= end:
            continue
        if source == "oi":
            values = {"quantity": number(row["sumOpenInterest"]), "usdt": number(row["sumOpenInterestValue"])}
        elif source == "taker":
            values = {"buy": number(row["buyVol"]), "sell": number(row["sellVol"])}
            values["ratio"] = number(row["buySellRatio"]) if values["sell"] else None
        else:
            values = {"long": number(row["longAccount"]), "short": number(row["shortAccount"])}
            values["ratio"] = number(row["longShortRatio"]) if values["short"] else None
        if all(v is None or v >= 0 for v in values.values()):
            result[boundary] = {"source_time": stamp, **values}
    return result


def price_buckets(bars, start, end, origin):
    closed = {bar["timestamp"]: bar for bar in bars if bar.get("closed", True)}
    result = {}
    for stamp in range(start, end + STEP, STEP):
        minutes = [closed.get(t) for t in range(stamp - STEP, stamp, MINUTE)]
        if all(minutes):
            result[stamp] = {"source_time": stamp - STEP, "open": minutes[0]["open"],
                             "close": minutes[-1]["close"], "source": origin}
    return result


def change(first, last):
    return last / first - 1 if first and last is not None else None


def summarize_hour(rows, end):
    indexed = {r["timestamp"]: r for r in rows}
    current = indexed.get(end, {})
    baseline = indexed.get(end - HOUR, {}).get("oi") or {}
    window = [indexed.get(t, {}) for t in range(end - HOUR + STEP, end + STEP, STEP)]
    price_change = share = None
    price_tail = []
    for row in window:
        if row.get("price"):
            price_tail.append(row["price"])
        else:
            price_tail.clear()
    if price_tail:
        price_change = change(price_tail[0]["open"], price_tail[-1]["close"])
    if all(row.get("taker") for row in window):
        buy = sum(row["taker"]["buy"] for row in window)
        total = buy + sum(row["taker"]["sell"] for row in window)
        share = buy / total if total else None
    return {
        **({"price_minutes": 5 * len(price_tail)} if 0 < len(price_tail) < 12 else {}),
        "timestamp": end, "price_change": price_change, "buy_share": share,
        "oi_change": change(baseline.get("quantity"), (current.get("oi") or {}).get("quantity")),
        **{source: current.get(source) for source in ENDPOINTS},
    }


def summary_readings(summary):
    values = {field: summary[field] for field in ("price_change", "oi_change", "buy_share")}
    values["account_ratio"] = (summary["accounts"] or {}).get("ratio")
    return {field: {"value": value, "timestamp": summary["timestamp"],
                    **({"available_minutes": summary["price_minutes"]} if field == "price_change" and summary.get("price_minutes") else {})}
            for field, value in values.items() if value is not None}


def list_metrics(rows, current):
    """Find each column's latest complete calculation, keeping its original boundary."""
    end = current["timestamp"]
    readings = summary_readings(current)
    for age in range(STEP, LIST_METRIC_MAX_AGE + 1, STEP):
        if len(readings) == 4:
            break
        for field, reading in summary_readings(summarize_hour(rows, end - age)).items():
            readings.setdefault(field, reading)
    return readings
