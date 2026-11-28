"""Frozen inputs from retired opening strategies for execution/exit compatibility tests."""
import json
from pathlib import Path


def historical_signal(version, side):
    records = json.loads((Path(__file__).parent / "fixtures/historical_opening_signals.json").read_text())
    data = records[f"{version}:{side}"]
    branch = data.pop("branch")
    return {"symbol": "NVDA.US", "trading_date": data["as_of"][:10], "as_of": data["as_of"],
            "opportunities": {**data, "primary": branch, "branches": [branch]}}
