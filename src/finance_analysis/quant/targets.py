"""Production target semantics owned by model type, not by admin input."""

from __future__ import annotations

from typing import Any, Mapping

from finance_analysis.quant.models import QLIB_TRAINABLE_MODEL_KEYS  # pragma: allowlist secret

DEFAULT_PREDICTION_HORIZON = 5
SHARED_ENTRY_PRICE = "open"
SHARED_EXIT_PRICE = "close"

_CROSS_SECTION = "cross_section_lgbm"
_TIME_SERIES = "time_series_lgbm"


def production_target_config(model_key: str, prediction_horizon: int = DEFAULT_PREDICTION_HORIZON) -> dict[str, Any]:
    """Return the only supported target contract for a trainable Qlib model."""
    if model_key not in QLIB_TRAINABLE_MODEL_KEYS:
        raise ValueError(f"Unknown model_key: {model_key}")
    horizon = int(prediction_horizon)
    if horizon < 1:
        raise ValueError("prediction_horizon must be positive")
    if model_key == _CROSS_SECTION:
        semantics = {"benchmark": "market", "excess_return": True}
    else:
        semantics = {"benchmark": "none", "excess_return": False}
    return {
        "prediction_horizon": horizon,
        "entry_price": SHARED_ENTRY_PRICE,
        "exit_price": SHARED_EXIT_PRICE,
        **semantics,
    }


def resolve_target_config(
    model_key: str,
    raw: Mapping[str, Any] | None,
    prediction_horizon: int = DEFAULT_PREDICTION_HORIZON,
) -> dict[str, Any]:
    """Ignore caller-supplied CS/TS semantics and apply the model-type contract."""
    del raw
    return production_target_config(model_key, prediction_horizon)


def stored_target_matches_production(model_key: str, stored: Mapping[str, Any] | None) -> bool:
    """Detect legacy runs whose stored labels do not match current model semantics."""
    expected = production_target_config(model_key)
    # Historical TargetConfig defaults were the cross-section contract.
    actual = {
        "benchmark": "market",
        "excess_return": True,
        "entry_price": SHARED_ENTRY_PRICE,
        "exit_price": SHARED_EXIT_PRICE,
        **dict(stored or {}),
    }
    return (
        actual.get("benchmark") == expected["benchmark"]
        and bool(actual.get("excess_return")) is expected["excess_return"]
        and actual.get("entry_price") == expected["entry_price"]
        and actual.get("exit_price") == expected["exit_price"]
    )


__all__ = [
    "DEFAULT_PREDICTION_HORIZON",
    "production_target_config",
    "resolve_target_config",
    "stored_target_matches_production",
]
