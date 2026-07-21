"""Canonical price modes used by quant research and Qlib artifacts."""

from __future__ import annotations

from enum import StrEnum


class PriceMode(StrEnum):
    RAW = "raw"
    FORWARD_ADJUSTED = "forward_adjusted"


DEFAULT_QUANT_PRICE_MODE = PriceMode.FORWARD_ADJUSTED
ADJUSTMENT_MODE_FORWARD = "forward"


def normalize_price_mode(value: str | PriceMode) -> PriceMode:
    try:
        return PriceMode(str(value))
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in PriceMode)
        raise ValueError(f"Unsupported price_mode={value!r}; expected one of: {allowed}") from exc


__all__ = [
    "ADJUSTMENT_MODE_FORWARD",
    "DEFAULT_QUANT_PRICE_MODE",
    "PriceMode",
    "normalize_price_mode",
]
