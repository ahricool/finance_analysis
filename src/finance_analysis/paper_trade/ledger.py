"""Attribute only exchange-confirmed fills linked to FA intents."""

from .strategy import D


def claimed_intents(intents):
    # An observed/queued intent never reached the exchange. Client ID alone
    # is insufficient; the durable claim and symbol must agree.
    return {i["id"]: i for i in intents if i["action"] != "CANCEL" and i.get("payload", {}).get("exchange_request")}


def intent_owner(by_client, row, field):
    intent = by_client.get(row.get(field))
    return intent if intent and intent["symbol"] == row["symbol"] else None


def attribution(intents, orders, algos):
    by_client = claimed_intents(intents)
    result = {}
    for row in orders:
        intent = intent_owner(by_client, row, "clientOrderId")
        if intent:
            result[(row["symbol"], str(row["orderId"]))] = intent
    for row in algos:
        intent = intent_owner(by_client, row, "clientAlgoId")
        if intent and row.get("actualOrderId"):
            result[(row["symbol"], str(row["actualOrderId"]))] = intent
    return result


def attributed_trades(intents, orders, algos, trades):
    owners = attribution(intents, orders, algos)
    result = []
    for row in trades:
        owner = owners.get((row["symbol"], str(row["orderId"])))
        item = {
            **row,
            "strategy": owner.get("strategy") if owner else None,
            "source": "STRATEGY" if owner and owner.get("strategy") else "FA_MANUAL" if owner else "EXTERNAL",
            "intent_action": owner.get("action") if owner else None,
            "intent_id": owner.get("id") if owner else None,
            "strategy_type": (
                owner["payload"].get("strategy_type", "ema_cross")
                if owner and owner.get("strategy") and owner["action"] == "SIGNAL" else None
            ),
            "net_excluding_funding": (
                str(D(row["realizedPnl"]) - D(row["commission"])) if row.get("commissionAsset") == "USDT" else None
            ),
        }
        result.append(item)
    return result


def ownership(symbol, positions, trades):
    matching = [p for p in positions if p["symbol"] == symbol and D(p["positionAmt"])]
    actual = sum((D(p["positionAmt"]) for p in matching), D(0))
    if any(p.get("positionSide", "BOTH") != "BOTH" for p in matching):
        return actual, False, True
    managed = D(0)
    conflict = False
    for trade in sorted((t for t in trades if t["symbol"] == symbol), key=lambda t: (t["time"], int(t["id"]))):
        if trade["strategy"] == symbol:
            managed += D(trade["qty"]) * (1 if trade["side"] == "BUY" else -1)
            if managed == 0:
                conflict = False
        elif managed:
            conflict = True
    return actual, bool(actual and managed == actual and not conflict), bool(conflict or actual != managed)


def performance(symbol, trades, income, strategy_type=None):
    """Round trips from attributable fills; funding only while exclusively owned."""
    qty = D(0)
    net = D(0)
    completed = []
    started = None
    trade_net = D(0)
    contaminated = False
    cycle_type = None
    timeline = [(t["time"], 0, t) for t in trades if t["symbol"] == symbol]
    timeline += [(i["time"], 1, i) for i in income if i.get("symbol") == symbol and i["incomeType"] == "FUNDING_FEE"]
    for stamp, kind, row in sorted(timeline, key=lambda x: (x[0], x[1], int(x[2].get("id", 0)))):
        if kind:
            if qty and not contaminated and row.get("asset") == "USDT":
                trade_net += D(row["income"])
            continue
        if row.get("strategy") != symbol:
            if qty:
                contaminated = True
            continue
        if not qty:
            started, trade_net, contaminated = stamp, D(0), False
            cycle_type = row.get("strategy_type") or "ema_cross"
        if row.get("strategy_type") and row["strategy_type"] != cycle_type:
            contaminated = True
        if row.get("commissionAsset") != "USDT":
            contaminated = True
        trade_net += D(row["realizedPnl"]) - D(row["commission"])
        qty += D(row["qty"]) * (1 if row["side"] == "BUY" else -1)
        if not qty:
            if not contaminated and (strategy_type is None or cycle_type == strategy_type):
                net += trade_net
                completed.append((trade_net, stamp - started))
            started = None
    if not completed:
        return {"trades": 0, "win_rate": None, "average_hold_ms": None, "net": None, "max_drawdown": None}
    balance = peak = drawdown = D(0)
    for pnl, _ in completed:
        balance += pnl
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    return {
        "trades": len(completed),
        "win_rate": str(D(sum(pnl > 0 for pnl, _ in completed)) / len(completed)),
        "average_hold_ms": sum(duration for _, duration in completed) // len(completed),
        "net": str(net),
        "max_drawdown": str(drawdown),
    }
