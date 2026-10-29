"""Offline coverage audit of exported public Instrument/reference classifications.

Inputs contain no credentials: stocks=[{market, code, listing_status, metadata}],
optional etfs=[{code}], CN reference=[{industry_code, industry_name, stock_code}].
Run with PYTHONPATH=src; this script never connects to a database or writes it.
"""

import argparse
from collections import defaultdict
import json

from finance_analysis.stocks.industry_etf import (
    CN_INDUSTRY_ETF,
    MAPPING_VERSION,
    US_INDUSTRY_ETF,
    resolve_industry_etf,
)


def summarize(stocks, memberships=(), available_etfs=None):
    """Count unique securities, separating current listings from delisted rows."""
    cn_codes = defaultdict(set)
    for member in memberships:
        if member.get("stock_code"):
            cn_codes[member["stock_code"]].add(member["industry_code"])
    groups = defaultdict(lambda: dict(total=0, classified=0, covered=0, multiple_proxies=0))
    unknown = set()
    observed = {"US": set(), "CN": set()}
    mapped = {"US": set(), "CN": set()}
    seen = set()
    for stock in stocks:
        identity = (stock["market"], stock["code"])
        if identity in seen:
            raise ValueError(f"Duplicate Instrument identity: {identity}")
        seen.add(identity)
        market, code = identity
        group = groups[f"{market}:{stock['listing_status']}"]
        group["total"] += 1
        classification = (stock.get("metadata") or {}).get("classification") or {}
        if market == "US":
            sector, industry = classification.get("sector"), classification.get("industry")
            keys = [(sector, industry)] if sector and industry else []
            proxies = [resolve_industry_etf(market, industry, sector=sector)] if keys else []
            registry = US_INDUSTRY_ETF
        elif market == "CN":
            keys = sorted(cn_codes[code])
            proxies = [resolve_industry_etf(market, key) for key in keys]
            registry = CN_INDUSTRY_ETF
        else:
            keys, proxies, registry = [], [], {}
        group["classified"] += bool(keys)
        codes = set()
        for key, proxy in zip(keys, proxies):
            observed[market].add(key)
            if key not in registry:
                unknown.add((market, str(key)))
            if proxy.etf_code and (available_etfs is None or proxy.etf_code in available_etfs):
                mapped[market].add(key)
                codes.add(proxy.etf_code)
        group["covered"] += bool(codes)
        group["multiple_proxies"] += len(codes) > 1
    for group in groups.values():
        group["coverage_pct"] = round(100 * group["covered"] / group["total"], 2) if group["total"] else None
        group["classified_coverage_pct"] = (
            round(100 * group["covered"] / group["classified"], 2) if group["classified"] else None
        )
    return dict(
        mapping_version=MAPPING_VERSION,
        groups=dict(sorted(groups.items())),
        industries={market: dict(observed=len(keys), mapped=len(mapped[market])) for market, keys in observed.items()},
        unreviewed=sorted(unknown),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instruments_json")
    parser.add_argument("--cn-reference")
    args = parser.parse_args()
    with open(args.instruments_json) as handle:
        snapshot = json.load(handle)
    memberships = []
    if args.cn_reference:
        with open(args.cn_reference) as handle:
            memberships = json.load(handle)
    etfs = {row["code"] for row in snapshot["etfs"]} if "etfs" in snapshot else None
    print(json.dumps(summarize(snapshot["stocks"], memberships, etfs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
