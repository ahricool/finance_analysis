import runpy
from pathlib import Path

import pytest

validate = runpy.run_path(str(Path(__file__).parents[2] / "scripts/validate_confluence_snapshot.py"))["validate"]


def test_offline_validation_replays_real_shape_and_checks_repeatability():
    day = "2026-10-28"
    sources = {
        key: [] for key in ("macro", "etf", "industry", "trend", "quant", "options", "sentiment", "dragon_tiger")
    }
    sources["macro"] = [dict(trade_date=day, risk_score=90)]
    sources["trend"] = [dict(trade_date=day, instrument_id=1, state="TRENDING", alpha_score=90)]
    result = validate({"US": dict(day=day, stocks=[dict(id=1, code="TEST.US", name="Test")], sources=sources)})
    assert result["US"]["rerun_stable"]
    assert result["US"]["summary"]["count"] == 1
    assert result["US"]["snapshot"]["items"][0]["code"] == "TEST.US"
    with pytest.raises(ValueError):
        validate({"US": dict(errors={"macro": "failed"})})
