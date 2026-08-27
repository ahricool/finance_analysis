"""A-share-only ETF rotation universe (CN listed, excluding overseas QDII)."""

from __future__ import annotations

from finance_analysis.etf_rotation.universe import ETFUniverseMember, enabled_etfs

A_SHARE_SUFFIXES = (".SH", ".SZ")
EXCLUDED_A_SHARE_CATEGORIES = frozenset({"OVERSEAS_INDEX"})


def a_share_etfs() -> tuple[ETFUniverseMember, ...]:
    """Return enabled CN ETFs listed on SH/SZ, excluding overseas-index trackers."""
    return tuple(
        member
        for member in enabled_etfs("CN")
        if member.code.endswith(A_SHARE_SUFFIXES) and member.category not in EXCLUDED_A_SHARE_CATEGORIES
    )


__all__ = ["A_SHARE_SUFFIXES", "EXCLUDED_A_SHARE_CATEGORIES", "a_share_etfs"]
