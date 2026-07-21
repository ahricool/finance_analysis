"""Price-mode contract shared by Qlib training and prediction tasks."""

FORWARD_ADJUSTED_PRICE_MODE = "forward_adjusted"


def require_forward_adjusted_manifest(manifest: dict) -> str:
    price_mode = manifest.get("price_mode")
    if price_mode != FORWARD_ADJUSTED_PRICE_MODE:
        raise ValueError(
            f"Production Qlib tasks require price_mode={FORWARD_ADJUSTED_PRICE_MODE}; "
            f"dataset manifest uses {price_mode!r}"
        )
    return price_mode


__all__ = ["FORWARD_ADJUSTED_PRICE_MODE", "require_forward_adjusted_manifest"]
