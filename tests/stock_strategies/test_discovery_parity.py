"""Replay frozen original discovery engine outputs, not implementation-derived expectations."""

import json
from datetime import date
from pathlib import Path

import pytest

from finance_analysis.stock_strategies.engine import advance, initial_state
from finance_analysis.stock_strategies.features import DailyInputs
from finance_analysis.stock_strategies.registry import STRATEGIES

REFERENCE = json.loads((Path(__file__).parent / "fixtures/discovery_engine.json").read_text())


@pytest.mark.parametrize("key", ["ma_dd30", "ma_dd25", "ma_atr3", "momentum60"])
def test_frozen_discovery_daily_nav_and_every_fill(key):
    spec = next(s for s in STRATEGIES if s.key == key)
    state = initial_state()
    start = date.fromisoformat(REFERENCE["inputs"][0]["date"])
    marks = {"SPY.US": {r["date"]: 100 for r in REFERENCE["inputs"]}}
    for code in ("A.US", "B.US"):
        marks[code] = {r["date"]: r["features"][code]["close"] for r in REFERENCE["inputs"]}
    nav, fills = [], []
    for index, row in enumerate(REFERENCE["inputs"]):
        features = dict(row["features"], **{"SPY.US": dict(valid=True, close=100)})
        data = DailyInputs(
            market="US",
            day=date.fromisoformat(row["date"]),
            next_day=date.fromisoformat(row["next_date"]),
            month_end=row["month_end"],
            features=features,
            instruments={c: dict(name=c, type="STOCK") for c in ("A.US", "B.US")},
            stocks=("A.US", "B.US"),
            etfs=(),
            breadth_codes=("A.US", "B.US"),
            prices=marks,
            benchmark="SPY.US",
        )
        state, snapshot = advance(spec, state, data, start)
        if index:
            nav.append(snapshot["nav"])
            fills.extend(
                [index - 1, f["code"], f["action"], f["quantity"] * (1 if f["action"] == "BUY" else -1), f["price"]]
                for f in snapshot["payload"]["fills"]
            )
    expected = REFERENCE["cases"][key]
    assert nav == pytest.approx(expected["nav"], rel=1e-10, abs=1e-5)
    assert len(fills) == len(expected["fills"])
    for actual, original in zip(fills, expected["fills"]):
        assert actual[:3] == original[:3]
        assert actual[3:] == pytest.approx(original[3:], rel=1e-10)
