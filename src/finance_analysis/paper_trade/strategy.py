"""Pure signal and Decimal order sizing; no exchange or persistence I/O."""

from decimal import Decimal, ROUND_DOWN

MINUTE = 60_000
PERIOD = 5 * MINUTE


def D(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite quantity or price")
    return result


def closed_closes(bars, now, required):
    # The collector refreshes the trailing minutes. Allow a short settling
    # interval and require a current-minute observation as evidence of refresh.
    end = now // PERIOD * PERIOD
    if now - end < 15_000 or now - end > 90_000:
        return None
    indexed = {bar["timestamp"]: bar for bar in bars}
    if now // MINUTE * MINUTE not in indexed:
        return None
    start = end - required * PERIOD
    if any(stamp not in indexed or indexed[stamp].get("closed") is False
           for stamp in range(start, end, MINUTE)):
        return None
    return end, [D(indexed[stamp - MINUTE]["close"]) for stamp in range(start + PERIOD, end + 1, PERIOD)]


def ema(values, period):
    alpha = D(2) / D(period + 1)
    result = values[0]
    for value in values[1:]:
        result += alpha * (value - result)
    return result


def ema_cross(closes, config):
    fast, slow = config["fast"], config["slow"]
    pf, ps = ema(closes[:-1], fast), ema(closes[:-1], slow)
    cf, cs = ema(closes, fast), ema(closes, slow)
    direction = "LONG" if pf <= ps and cf > cs else "SHORT" if pf >= ps and cf < cs else None
    return direction, {"fast_ema": str(cf), "slow_ema": str(cs), "previous_fast": str(pf), "previous_slow": str(ps)}


STRATEGIES = {"ema_cross": ema_cross}


def contract_rule(rules, symbol):
    rule = next((row for row in rules if row["symbol"] == symbol), None)
    if (
        not rule
        or rule.get("status") != "TRADING"
        or rule.get("quoteAsset") != "USDT"
        or rule.get("marginAsset") != "USDT"
    ):
        raise ValueError("DEMO_SYMBOL_UNAVAILABLE")
    if rule.get("contractType") not in {"PERPETUAL", "TRADIFI_PERPETUAL"}:
        raise ValueError("DEMO_NOT_PERPETUAL")
    return rule


def filters(rule):
    return {item["filterType"]: item for item in rule["filters"]}


def floor_step(value, step):
    return (D(value) / D(step)).to_integral_value(rounding=ROUND_DOWN) * D(step)


def validate_order(rule, order, reference):
    f = filters(rule)
    market = order["type"] in {"MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"}
    if rule.get("orderTypes") and order["type"] not in rule["orderTypes"]:
        raise ValueError("DEMO_ORDER_TYPE_UNAVAILABLE")
    lot = f.get("MARKET_LOT_SIZE", f["LOT_SIZE"]) if market else f["LOT_SIZE"]
    qty = D(order["quantity"])
    step = D(lot["stepSize"])
    if qty <= 0 or qty < D(lot["minQty"]) or qty > D(lot["maxQty"]) or (step and qty % step):
        raise ValueError("DEMO_QUANTITY_FILTER")
    price = D(reference)
    for field in ("price", "triggerPrice"):
        if field in order:
            price = D(order[field])
            pf = f["PRICE_FILTER"]
            tick = D(pf["tickSize"])
            if (
                price <= 0
                or price < D(pf["minPrice"])
                or (D(pf["maxPrice"]) and price > D(pf["maxPrice"]))
                or (tick and price % tick)
            ):
                raise ValueError("DEMO_PRICE_FILTER")
    if order.get("reduceOnly") != "true" and qty * price < D(f.get("MIN_NOTIONAL", {}).get("notional", 0)):
        raise ValueError("DEMO_MIN_NOTIONAL")
    return qty


def sized_quantity(rule, notional, price):
    f = filters(rule)
    lot = f.get("MARKET_LOT_SIZE", f["LOT_SIZE"])
    return floor_step(D(notional) / D(price), D(lot["stepSize"]) or D(f["LOT_SIZE"]["stepSize"]))
