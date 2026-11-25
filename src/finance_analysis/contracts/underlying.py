"""Identify the detail target without treating contract prices as underlying prices."""

# These exchange aliases do not identify a supported US/HK/CN cash security.
UNSUPPORTED_ALIASES = {"SKHYNIX", "SPCX", "ANT", "SKHY", "SNXX", "XAU", "XAG", "CL"}


def underlying_symbol(symbol: str, category: str, base_asset: str | None = None) -> str | None:
    base = (base_asset or (symbol[:-4] if symbol.endswith("USDT") else "")).strip().upper()
    if not base or not base.isascii() or not base.isalnum() or len(base) > 32:
        return None
    if category in {"COIN", "加密货币"}:
        return f"{base}.CRYPTO"
    if base not in UNSUPPORTED_ALIASES and category in {"EQUITY", "美股", "ETF"}:
        return f"{base}.US"
    return f"{base}.OTHER"
