"""JSON views shared by holdings HTTP and live portfolio snapshots."""


def _json_dec(value):
    return None if value is None else format(value, "f")


def _account_payload(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "market": item["market"],
        "cash": _json_dec(item["cash"]),
        "currency": item["currency"],
    }


def _position_payload(item: dict) -> dict:
    return {
        "id": item["id"],
        "account_id": item["account_id"],
        "market": item["market"],
        "symbol": item["symbol"],
        "asset_type": item["asset_type"],
        "quantity": _json_dec(item["quantity"]),
        "average_cost": _json_dec(item["average_cost"]),
        "opened_at": item.get("opened_at"),
        "closed_at": item.get("closed_at"),
        "lots": [
            {
                "id": lot["id"],
                "role": lot["role"],
                "entry_price": _json_dec(lot["entry_price"]),
                "remaining_quantity": _json_dec(lot["remaining_quantity"]),
                "entry_time": lot["entry_time"],
            }
            for lot in item.get("lots") or []
        ],
    }
