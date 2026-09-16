"""Canonical Fuyao fundamentals with independent, fail-open data blocks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from finance_analysis.market_review.trading_calendar import get_trading_days_between

from .providers.fuyao import FuyaoProvider, SHANGHAI, number, timestamp


class FuyaoFundamentalAdapter:
    def __init__(self, provider: FuyaoProvider):
        self.provider = provider

    def get_fundamental_bundle(self, stock_code: str) -> dict:
        symbol = self.provider._symbol(stock_code)
        result = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "valuation": {},
            "source_chain": [],
            "errors": [],
        }

        def fetch(path, **params):
            try:
                data = self.provider._get(path, **params)
                if path.endswith("indicators"):
                    abilities = data.get("abilities")
                    if not isinstance(abilities, list) or any(
                        not isinstance(a, dict)
                        or not isinstance(a.get("indicators"), list)
                        or any(not isinstance(i, dict) or "index_id" not in i for i in a["indicators"])
                        for a in abilities
                    ):
                        raise ValueError("Fuyao invalid indicators")
                else:
                    self.provider._items(data)
                if data.get("thscode", symbol) != symbol:
                    raise ValueError("Fuyao unexpected fundamental symbol")
                result["source_chain"].append(path)
                return data
            except Exception as exc:
                result["errors"].append(str(exc))
                return {}

        statements = {}
        for kind in ("income-statements", "cash-flow-statements", "balance-sheets"):
            data = fetch(f"/api/a-share/financials/{kind}", thscode=symbol, period="quarterly", limit=4)
            rows = [
                r
                for r in data.get("item", [])
                if r.get("thscode") == symbol and number(r.get("period_end_ms")) is not None
            ]
            if rows:
                statements[kind] = max(rows, key=lambda r: r["period_end_ms"])
        income = statements.get("income-statements", {})
        cash = statements.get("cash-flow-statements", {})
        balance = statements.get("balance-sheets", {})
        # Never combine different quarters into one financial_report.
        report_ms = max((r["period_end_ms"] for r in statements.values()), default=None)
        report = {}
        if report_ms:
            day = timestamp(report_ms).astimezone(SHANGHAI).date()
            report["report_date"] = day.isoformat()
            disclosures = [
                timestamp(r.get("report_date_ms")) for r in statements.values() if r.get("period_end_ms") == report_ms
            ]
            disclosures = [d for d in disclosures if d is not None]
            if disclosures:
                report["announcement_date"] = max(disclosures).astimezone(SHANGHAI).date().isoformat()
            for row, mapping in (
                (
                    income,
                    {
                        "revenue": "operating_income",
                        "net_profit_parent": "parent_holder_net_profit",
                        "net_profit": "net_profit",
                    },
                ),
                (cash, {"operating_cash_flow": "act_cash_flow_net"}),
                (
                    balance,
                    {
                        "total_assets": "assets_total",
                        "total_liabilities": "total_debt",
                        "total_equity": "holder_equity_total",
                    },
                ),
            ):
                if row.get("period_end_ms") == report_ms:
                    report.update({key: number(row.get(raw)) for key, raw in mapping.items()})
            indicators = fetch(
                "/api/a-share/financials/indicators", thscode=symbol, report=f"{day.year}-{(day.month - 1) // 3 + 1}"
            )
            values = {
                i["index_id"]: number(i.get("value"))
                for ability in indicators.get("abilities", [])
                for i in ability.get("indicators", [])
            }
            mapping = {
                "revenue_yoy": "operating_income_yoy_growth_ratio",
                "net_profit_yoy": "net_profit_yoy_growth_ratio",
                "roe": "index_weighted_avg_roe",
                "gross_margin": "sale_gross_margin",
            }
            result["growth"] = {key: values.get(raw) for key, raw in mapping.items()}
            # The live API also emits these calculated growth IDs. They use
            # percentage points; parent profit matches net_profit_parent above.
            for key, live_id in (
                ("revenue_yoy", "calculate_operating_income_yoy_growth_ratio"),
                ("net_profit_yoy", "calculate_parent_holder_net_profit_yoy_growth_ratio"),
            ):
                if result["growth"][key] is None:
                    result["growth"][key] = values.get(live_id)
            report["roe"] = result["growth"]["roe"]
            result["earnings"]["financial_report"] = report
        data = fetch("/api/a-share/valuations/snapshot", thscodes=symbol)
        row = next((r for r in data.get("item", []) if r.get("thscode") == symbol), {})
        mapping = {
            "pe_ratio": "pe_ttm",
            "pe_ttm": "pe_ttm",
            "pe_mrq": "pe_mrq",
            "pb_ratio": "pb_mrq",
            "pb_mrq": "pb_mrq",
            "ps_ttm": "ps_ttm",
            "pcf_ttm": "pcf_ttm",
        }
        result["valuation"] = {key: number(row.get(raw)) for key, raw in mapping.items()}
        actions = fetch("/api/a-share/corporate-actions/adjustment-factors", thscode=symbol)
        today = datetime.now(SHANGHAI).date()
        events = {}
        for row in actions.get("item", []):
            ex_time, amount = timestamp(row.get("ex_date_ms")), number(row.get("dividend_per_share"))
            if ex_time is None or amount is None or amount <= 0:
                continue
            day = ex_time.astimezone(SHANGHAI).date()
            if day > today:
                continue
            events[(day, amount)] = {
                "event_date": day.isoformat(),
                "ex_dividend_date": day.isoformat(),
                "cash_dividend_per_share": amount,
                "is_pre_tax": True,
            }
        ordered = [events[key] for key in sorted(events, reverse=True)]
        ttm = [value for (day, _), value in events.items() if today - timedelta(days=365) <= day <= today]
        if ordered:
            result["earnings"]["dividend"] = {
                "events": ordered[:5],
                "ttm_event_count": len(ttm),
                "ttm_cash_dividend_per_share": sum(r["cash_dividend_per_share"] for r in ttm) if ttm else None,
                "coverage": "cash_dividend_pre_tax",
                "as_of": today.isoformat(),
            }
        if report or ordered or any(v is not None for v in result["valuation"].values()):
            result["status"] = "partial"
        return result

    def get_dragon_tiger_flag(self, stock_code: str, lookback_days: int = 20) -> dict:
        """Aggregate unique listing days over the requested calendar-day window."""
        result = {
            "status": "failed",
            "is_on_list": False,
            "recent_count": 0,
            "latest_date": None,
            "source_chain": [],
            "errors": [],
        }
        try:
            symbol = self.provider._symbol(stock_code)
            latest = self.provider._get("/api/a-share/special-data/dragon-tiger-list", board_type="all")
            end = date.fromisoformat(latest["trade_date"])
            today = datetime.now(SHANGHAI).date()
            start = today - timedelta(days=max(1, min(lookback_days, 365)))
            days = get_trading_days_between("cn", start, min(end, today)) if start <= end else []
            observed = {}
            if start <= end <= today:
                observed[end] = latest

            def fetch(day):
                try:
                    data = self.provider._get(
                        "/api/a-share/special-data/dragon-tiger-list", board_type="all", date=day.isoformat()
                    )
                    if data.get("trade_date") != day.isoformat() or not isinstance(data.get("stock_items"), list):
                        raise ValueError("Fuyao unexpected dragon-tiger date or rows")
                    return day, data, None
                except Exception as exc:
                    return day, None, str(exc)

            # Bounded public requests; an unavailable day cannot erase other days.
            with ThreadPoolExecutor(max_workers=3) as pool:
                for day, data, error in pool.map(fetch, [d for d in days if d not in observed]):
                    if error:
                        result["errors"].append(error)
                    else:
                        observed[day] = data
            matched = [
                day
                for day, data in observed.items()
                if any(row.get("thscode") == symbol for row in data.get("stock_items", []))
            ]
            result.update(
                status="partial" if result["errors"] else "ok",
                is_on_list=bool(matched),
                recent_count=len(matched),
                latest_date=max(matched).isoformat() if matched else None,
                source_chain=["fuyao:dragon-tiger-list"],
            )
        except Exception as exc:
            result["errors"].append(str(exc))
        return result
