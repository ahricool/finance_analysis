"""Pure USD-M data normalization shared by isolated Demo and Live stores."""


def normalize_ids(source):
    row = dict(source)
    for field in ("orderId", "algoId", "actualOrderId", "id", "tranId", "tradeId"):
        if field in row and row[field] is not None:
            row[field] = str(row[field])
    return row


def usdt_perpetual_symbols(rules):
    return {
        row["symbol"]
        for row in rules
        if row.get("contractType") in {"PERPETUAL", "TRADIFI_PERPETUAL"}
        and row.get("marginAsset") == row.get("quoteAsset") == "USDT"
    }


def reconciliation_orders(snapshot):
    """Previously open orders are retained across incomplete snapshots."""
    snapshot = snapshot or {}
    orders = (
        snapshot.get("reconcile_open_orders", []) + snapshot.get("open_orders", []) + snapshot.get("open_algos", [])
    )
    by_id = {}
    for order in orders:
        field = "algoId" if "algoId" in order else "orderId"
        by_id[(field, order["symbol"], str(order[field]))] = order
    return list(by_id.values())


def equity_history_point(payload):
    """Retain account equity history without duplicating full open-order/position snapshots."""
    account = payload.get("account", {})
    fields = (
        "totalMarginBalance",
        "totalWalletBalance",
        "availableBalance",
        "totalUnrealizedProfit",
        "totalInitialMargin",
    )
    return {
        "account": {field: account[field] for field in fields if field in account},
        "synced_at": payload.get("synced_at"),
    }
