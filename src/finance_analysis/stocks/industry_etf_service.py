"""Resolve current stock classifications to existing Rotation ETF proxies, DB-only."""

from finance_analysis.stocks.industry_etf import resolve_industry_etf


class StockETFProxyService:
    def __init__(self, instruments):
        self.instruments = instruments

    def resolve(self, instrument, industries):
        market = instrument.market
        if getattr(instrument, "instrument_type", "STOCK") != "STOCK":
            return dict(etf_proxies=[], etf_proxy_unavailable_reasons=["仅对股票提供行业ETF关联"])
        if market not in {"CN", "US"}:
            return dict(etf_proxies=[], etf_proxy_unavailable_reasons=["当前未维护该市场的行业ETF映射"])
        if not industries:
            return dict(etf_proxies=[], etf_proxy_unavailable_reasons=["暂无行业分类，无法关联ETF"])
        classification = (getattr(instrument, "instrument_metadata", None) or {}).get("classification") or {}
        candidates, unavailable = {}, []
        for industry in industries:
            proxy = resolve_industry_etf(
                market,
                classification.get("industry", "") if market == "US" else industry["code"],
                sector=classification.get("sector"),
            )
            reason = f"{industry['name']}：{proxy.reason}"
            if proxy.etf_code:
                reasons = candidates.setdefault(proxy.etf_code, [])
                if reason not in reasons:
                    reasons.append(reason)
            elif reason not in unavailable:
                unavailable.append(reason)
        names = self.instruments.rotation_etf_names(market, sorted(candidates)) if candidates else {}
        proxies = []
        for code, reasons in sorted(candidates.items()):
            if code not in names:
                unavailable.append(f"{code}：当前ETF轮动池中不可用")
                continue
            proxies.append(dict(code=code, name=names[code], reasons=reasons))
        return dict(etf_proxies=proxies, etf_proxy_unavailable_reasons=unavailable)
