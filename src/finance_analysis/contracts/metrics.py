"""Five-minute UTC ending boundaries shared by collection, storage and projection."""
from finance_analysis.integrations.crypto.binance import number

MINUTE = 60_000
STEP = 5 * MINUTE
HOUR = 12 * STEP
DAY = 24 * HOUR
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
    if all(row.get("price") for row in window):
        price_change = change(window[0]["price"]["open"], window[-1]["price"]["close"])
    if all(row.get("taker") for row in window):
        buy = sum(row["taker"]["buy"] for row in window)
        total = buy + sum(row["taker"]["sell"] for row in window)
        share = buy / total if total else None
    return {
        "timestamp": end, "price_change": price_change, "buy_share": share,
        "oi_change": change(baseline.get("quantity"), (current.get("oi") or {}).get("quantity")),
        **{source: current.get(source) for source in ENDPOINTS},
    }
