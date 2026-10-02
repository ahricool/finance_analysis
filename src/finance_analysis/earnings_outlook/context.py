"""Bounded structured inputs, never substitutes remembered or fabricated live numbers."""

import statistics
from datetime import timedelta

from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.core.time import utc_now
from finance_analysis.market_review.us_postmarket_symbols import US_POSTMARKET_SECTOR_ETFS
from finance_analysis.market_review.trading_calendar import get_market_session_bounds
from .rules import NY, number, timestamp, schedule, trading_days
from .facts import raw_facts


def consensus(event):
    facts = raw_facts(event)
    result = {k: facts.get("consensus", {}).get(k) for k in ("eps", "revenue")}
    if result["eps"] is None and event.eps_estimate is not None:
        result["eps"] = dict(
            value=event.eps_estimate,
            quarter=event.reporting_period,
            currency=event.currency,
            unit="per_share",
            basis=None,
            source=event.provider,
            as_of=None,
            observed_at=str(event.last_seen_at),
            note="日历未提供 EPS 口径及预期更新时间",
        )
    return result


class ContextCollector:
    def __init__(self, repo, market=None):
        self.repo, self.market = repo, market or MarketDataService()

    def bars(self, symbols, now):
        days = trading_days(now.astimezone(NY).date() - timedelta(days=60), now.astimezone(NY).date())
        complete = [d for d in days if get_market_session_bounds("us", d)[1] <= now][-30:]
        if not complete:
            return {}
        result = self.market.get_daily_bars(
            symbols, complete[0], complete[-1], adjustment="forward", source_policy="db_only"
        )
        data = {}
        for symbol, rows in result.data.items():
            rows = sorted((r for r in rows if r.trade_date in complete), key=lambda r: r.trade_date)[-30:]
            if not rows:
                continue
            returns = [b.close / a.close - 1 for a, b in zip(rows, rows[1:]) if a.close > 0]
            trs = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(rows, rows[1:])]
            data[symbol] = dict(
                bars=[
                    dict(date=str(r.trade_date), open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
                    for r in rows
                ],
                return_pct=(rows[-1].close / rows[0].close - 1) * 100,
                volatility=statistics.stdev(returns) if len(returns) > 1 else None,
                atr14=statistics.mean(trs[-14:]) if len(trs) >= 14 else None,
                sessions=len(rows),
                as_of=str(rows[-1].trade_date),
            )
        return data

    def public(self, now):
        missing = []
        try:
            benchmarks = self.bars(["SPY.US", "QQQ.US", *US_POSTMARKET_SECTOR_ETFS], now)
        except Exception:
            benchmarks = {}
            missing.append("SPY/QQQ DB 日线不可用")
        # Existing public snapshots are read in a single short transaction.
        return dict(
            benchmarks={k: v for k, v in benchmarks.items() if k in {"SPY.US", "QQQ.US"}},
            sector_performance={
                k: dict(name=US_POSTMARKET_SECTOR_ETFS[k], **v)
                for k, v in benchmarks.items()
                if k in US_POSTMARKET_SECTOR_ETFS
            },
            **self.repo.market_context(now),
            missing_data=missing,
        )

    def collect(self, event, member, now, window, public):
        missing = list(public.get("missing_data", []))
        quote = None
        try:
            quote = self.market.get_realtime_quotes([member["symbol"]]).data.get(member["symbol"])
        except Exception:
            missing.append("最新报价读取失败")
        at = timestamp(quote.quote_time) if quote else None
        price = number(quote.price) if quote else None
        if not at or at > utc_now() or at >= window["cutoff"] or not price or price <= 0:
            price = None
            missing.append("价格或报价时间不可用")
        session = "unknown"
        if at:
            local = at.astimezone(NY)
            if local.date() in trading_days(local.date(), local.date()):
                opening, closing = get_market_session_bounds("us", local.date())
                session = "premarket" if local < opening else "regular" if local <= closing else "postmarket"
            else:
                session = "closed"
        try:
            technical = self.bars([member["symbol"]], now).get(member["symbol"])
        except Exception:
            technical = None
        if not technical or technical["sessions"] < 15:
            missing.append("不足15个完整交易日技术数据")
        facts = raw_facts(event)
        for key in ("analyst_revisions", "options_implied_range", "historical_reactions", "guidance"):
            if not facts.get(key):
                missing.append(f"{key}: 结构化数据不可用")
        return dict(
            event=schedule(event),
            time_certainty=(
                "explicit"
                if event.event_datetime
                else "session_only" if event.market_session in {"bmo", "amc"} else "date_only"
            ),
            company=member,
            data_cutoff=now.isoformat(),
            target_trading_date=str(window["target_trading_date"]),
            provisional=window["provisional"],
            assumption=window["assumption"],
            reference_price=price,
            reference_price_at=at.isoformat() if at else None,
            reference_price_session=session,
            price_stale=not at or now - at > timedelta(hours=24),
            technical=technical,
            market=public,
            consensus=consensus(event),
            valuation={"pe": quote.pe_ratio if quote else None, "pb": quote.pb_ratio if quote else None},
            historical_earnings=self.repo.history_events(event.symbol, event.event_date),
            guidance_evidence=facts.get("guidance"),
            analyst_revisions=facts.get("analyst_revisions"),
            options_implied_range=facts.get("options_implied_range"),
            historical_reactions=facts.get("historical_reactions"),
            missing_data=missing,
        )

    def actual(self, event, version, now):
        facts = raw_facts(event)
        actual = {k: facts.get("actual", {}).get(k) for k in ("eps", "revenue")}
        # Read historical calendar responses without persisting calendar/market data here.
        if any(actual[k] is None for k in ("eps", "revenue")):
            for source in self.market.get_calendar_sources().values():
                try:
                    result = source.fetch_earnings_calendar(
                        event.event_date, event.event_date, "US", symbols={event.symbol}
                    )
                    for row in result.events:
                        if row.get("symbol") != event.symbol or row.get("reporting_period") != event.reporting_period:
                            continue
                        normalized = raw_facts(row).get("actual", {})
                        for key in ("eps", "revenue"):
                            actual[key] = actual[key] or normalized.get(key)
                        if actual["eps"] is None and row.get("reported_eps") is not None:
                            actual["eps"] = dict(
                                value=row["reported_eps"],
                                quarter=row.get("reporting_period"),
                                currency=row.get("currency"),
                                unit="per_share",
                                basis=None,
                            )
                except Exception:
                    pass  # Pending: provider absence is not an invented result.
        if actual["eps"] is None and event.reported_eps is not None:
            actual["eps"] = dict(
                value=event.reported_eps,
                quarter=event.reporting_period,
                currency=event.currency,
                unit="per_share",
                basis=None,
            )
        actual["ohlc"] = None
        target = version.target_trading_date
        if now >= get_market_session_bounds("us", target)[1]:
            result = self.market.get_daily_bars(
                [event.symbol], target, target, adjustment="forward", source_policy="db_only"
            )
            row = next((r for r in result.data.get(event.symbol, []) if r.trade_date == target), None)
            if row and 0 < row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high:
                actual["ohlc"] = dict(
                    date=str(target),
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    adjustment="forward",
                    session="regular",
                )
        actual["missing_reason"] = "未取得同季度同口径实际值时不可比较；正常交易日日线未齐全时pending"
        return actual
